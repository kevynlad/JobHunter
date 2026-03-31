"""
src/db/connection.py
━━━━━━━━━━━━━━━━━━━
Stateless PostgreSQL connection helper para ambiente Serverless (Vercel).

GUARDRAIL: Em Serverless, o processo Python nasce e morre a cada request.
Usamos o Transaction Pooler do Supabase (porta 6543) — resolve para IPv4,
que a Vercel Lambda consegue acessar. A conexão direta (porta 5432) resolve
para IPv6 e é bloqueada pelo Lambda.

NOTA: O Transaction Pooler (PgBouncer) opera em "transaction mode" e NÃO
suporta SET/set_config de variáveis de sessão. Por isso, multi-tenant
isolation é feito via filtro explícito user_id em todas as queries (WHERE
user_id = %s), não via RLS session variables.
"""

import os
import logging
from contextlib import contextmanager

import psycopg2

logger = logging.getLogger(__name__)


@contextmanager
def get_conn(user_id: int | None = None):
    """
    Context manager que abre uma conexão direta e efêmera ao PostgreSQL
    via Transaction Pooler do Supabase (porta 6543, IPv4, compatível com Vercel).

    O parâmetro user_id é aceito para compatibilidade com a API existente,
    mas o isolamento de tenant é feito pelas queries (WHERE user_id = %s).
    """
    # POSTGRES_URL é injetado automaticamente pela integração Supabase ↔ Vercel
    # (Transaction Pooler, porta 6543, IPv4). DATABASE_URL é o fallback para dev local.
    dsn = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "Nenhuma URL de banco encontrada. "
            "Configure POSTGRES_URL (Supabase-Vercel integration) ou DATABASE_URL."
        )

    # psycopg2 rejeita parâmetros proprietários da URL do Supabase (ex: ?supa=base-pooler.x)
    # Removemos o query string para compatibilidade.
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(dsn)
    dsn = urlunparse(parsed._replace(query=""))

    conn = psycopg2.connect(dsn)
    try:
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
