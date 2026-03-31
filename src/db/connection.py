"""
src/db/connection.py
━━━━━━━━━━━━━━━━━━━
Stateless PostgreSQL connection helper para ambiente Serverless (Vercel).

GUARDRAIL: Em Serverless, o processo Python nasce e morre a cada request.
NÃO usamos Connection Pooling em memória (ThreadedConnectionPool) porque
a memória não persiste entre invocações. Cada request abre uma conexão
direta, usa e fecha — esse é o padrão correto para Vercel.
"""

import os
import logging
from contextlib import contextmanager

import psycopg2

logger = logging.getLogger(__name__)


@contextmanager
def get_conn(user_id: int | None = None):
    """
    Context manager que abre uma conexão direta e efêmera ao PostgreSQL.

    Projetado para ambientes Serverless (Vercel): abre, usa e fecha.
    Se user_id for fornecido, seta a variável de sessão para RLS/tenant isolation.
    Usa cursor padrão (tuplas) para compatibilidade com todos os módulos.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL não configurada no ambiente.")

    conn = psycopg2.connect(dsn)
    try:
        if user_id is not None:
            with conn.cursor() as cur:
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
        conn.close()
