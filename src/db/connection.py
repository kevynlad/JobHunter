"""
src/db/connection.py
━━━━━━━━━━━━━━━━━━━
PostgreSQL connection pool + tenant context helper.
Uses psycopg2 with a simple connection pool.
"""

import os
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.pool

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=0,
            maxconn=5,
            dsn=os.environ["DATABASE_URL"],
        )
    return _pool


def _get_valid_conn(pool):
    """Get a connection from the pool and ensure it is alive."""
    # Try up to max_conn times to clear out dead connections
    for _ in range(10):
        conn = pool.getconn()
        if conn.closed:
            pool.putconn(conn, close=True)
            continue
        
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            pool.putconn(conn, close=True)
    
    # If all else fails, just return a fresh one and hope for the best
    return pool.getconn()


@contextmanager
def get_conn(user_id: int | None = None):
    """
    Context manager that yields a psycopg2 connection scoped to a tenant.

    If user_id is provided, sets the PostgreSQL session variable that RLS
    policies read from. This ensures every query in this connection is
    automatically filtered to that user's rows.
    """
    pool = _get_pool()
    conn = _get_valid_conn(pool)
    
    try:
        if user_id is not None:
            with conn.cursor() as cur:
                # SET LOCAL scopes to current transaction
                cur.execute(
                    "SELECT set_config('app.current_user_id', %s, TRUE)",
                    (str(user_id),)
                )
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        pool.putconn(conn)


def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
