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
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# URL pública do projeto (não é segredo)
_SUPABASE_URL = "https://bixkyexjpvuedspgwwyl.supabase.co"


def get_client() -> Client:
    """
    Retorna um cliente Supabase autenticado com a service_role key.
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
