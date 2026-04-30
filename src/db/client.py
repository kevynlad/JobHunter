"""
src/db/client.py
━━━━━━━━━━━━━━━
Supabase SDK client — driver primário para ambientes Serverless (Vercel).

Usa HTTPS (porta 443) ao invés de TCP direto. Sem problemas de IPv6,
pooler ou autenticação de rede. Funciona em qualquer ambiente.

Variáveis necessárias:
  SUPABASE_URL         → https://bixkyexjpvuedspgwwyl.supabase.co
  SUPABASE_SERVICE_KEY → service_role key (Supabase → Settings → API)
"""

import os
import logging
from functools import lru_cache
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# URL pública do projeto (não é segredo)
_SUPABASE_URL = "https://bixkyexjpvuedspgwwyl.supabase.co"


@lru_cache(maxsize=1)
def get_client() -> Client:
    """
    Retorna um cliente Supabase autenticado com a service_role key.
    Cache: reutiliza a instância dentro do mesmo processo (GitHub Actions = horas).
    Em Serverless (Vercel), o processo morre a cada request — o cache não tem custo.

    A service_role key bypassa RLS — o isolamento de tenant é feito
    via filtros explícitos (user_id) em todas as queries.
    """
    url = os.environ.get("SUPABASE_URL", os.environ.get("NEXT_PUBLIC_SUPABASE_URL", _SUPABASE_URL))
    key = os.environ.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))

    if not key:
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY não configurada. "
            "Vá em Supabase → Settings → API → service_role key "
            "e configure como variável de ambiente."
        )

    return create_client(url, key)


@lru_cache(maxsize=16)
def get_vault_secret(secret_name: str) -> str | None:
    """
    Busca uma chave/segredo de forma segura no Supabase Vault.
    Usa uma stored procedure 'get_vault_secret' com SECURITY DEFINER.
    Requer SUPABASE_SERVICE_KEY no ambiente.
    """
    try:
        result = get_client().rpc("get_vault_secret", {"secret_name": secret_name}).execute()
        return result.data if result.data else None
    except Exception as e:
        logger.error(f"Erro ao buscar segredo do Vault '{secret_name}': {e}")
        return None
