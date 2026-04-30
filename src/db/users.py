"""
src/db/users.py
━━━━━━━━━━━━━━
User CRUD — Multi-tenant, sem BYOK.

Usa supabase-py (HTTPS) como driver — funciona em Vercel (sem TCP/IPv6).
O psycopg2 continua disponível via connection.py para o pipeline no GitHub Actions.

Campos por usuário:
  user_id, first_name, username  → identidade
  career_summary, career_vectors → perfil de carreira (núcleo do multi-tenant)
  search_config                  → configuração de busca por usuário (JSONB)
  onboarding_step                → fluxo de onboarding
  is_active                      → se o pipeline deve rodar para esse usuário
"""

import json
import logging

from src.db.client import get_client

logger = logging.getLogger(__name__)


def get_user(user_id: int) -> dict | None:
    """Fetch user row by PK."""
    result = (
        get_client()
        .table("users")
        .select(
            "user_id, first_name, username, "
            "career_summary, career_vectors, search_config, onboarding_step, is_active"
        )
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def upsert_user(user_id: int, first_name: str, username: str | None = None) -> dict:
    """Cria o usuário se não existir. Retorna o row do usuário."""
    result = (
        get_client()
        .table("users")
        .upsert(
            {"user_id": user_id, "first_name": first_name, "username": username},
            on_conflict="user_id",
        )
        .execute()
    )
    row = result.data[0]
    return {"user_id": row["user_id"], "onboarding_step": row.get("onboarding_step", "new")}


def set_career_profile(user_id: int, career_summary: str, career_vectors: dict):
    """Salva o resumo de carreira e os vetores de embedding, e ativa o usuário."""
    get_client().table("users").update({
        "career_summary":  career_summary,
        "career_vectors":  json.dumps(career_vectors),
        "onboarding_step": "ready",
        "is_active":       True,
    }).eq("user_id", user_id).execute()


def get_search_config(user_id: int) -> dict | None:
    """
    Retorna o search_config do usuário, ou None se não configurado.
    O matcher.py faz o fallback para config.py caso retorne None.
    """
    result = (
        get_client()
        .table("users")
        .select("search_config")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0].get("search_config")


def set_search_config(user_id: int, config: dict) -> bool:
    """
    Salva o search_config do usuário no banco.

    Estrutura esperada:
    {
        "career_paths": [
            {"name": "...", "queries": ["...", "..."], "weight": 1.0}
        ],
        "locations":     ["São Paulo, Brazil"],
        "include_remote": true,
        "max_days_old":  7
    }

    Retorna True se salvo com sucesso.
    """
    try:
        get_client().table("users").update({
            "search_config": config,
        }).eq("user_id", user_id).execute()
        logger.info(f"search_config salvo para user {user_id}: {len(config.get('career_paths', []))} paths")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar search_config para user {user_id}: {e}")
        return False


def get_active_users() -> list[dict]:
    """Retorna todos os usuários ativos com perfil configurado. Usado pelo pipeline cron."""
    result = (
        get_client()
        .table("users")
        .select(
            "user_id, first_name, career_summary, career_vectors, search_config"
        )
        .eq("is_active", True)
        .not_.is_("career_summary", "null")
        .execute()
    )
    return result.data
