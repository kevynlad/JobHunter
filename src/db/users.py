"""
src/db/users.py
━━━━━━━━━━━━━━
User CRUD + BYOK key encryption/decryption.

Usa supabase-py (HTTPS) como driver — funciona em Vercel (sem TCP/IPv6).
O psycopg2 continua disponível via connection.py para o pipeline
no GitHub Actions.
"""

import os
import json
import logging
from cryptography.fernet import Fernet

from src.db.client import get_client

logger = logging.getLogger(__name__)

# MASTER_KEY vive apenas nas env vars da Vercel / GitHub Actions — nunca no DB
_cipher = Fernet(os.environ["ENCRYPTION_MASTER_KEY"].encode())


def encrypt_key(raw: str) -> str:
    return _cipher.encrypt(raw.encode()).decode()


def decrypt_key(encrypted: str) -> str:
    return _cipher.decrypt(encrypted.encode()).decode()


def _decrypt_user(row: dict) -> dict:
    """Decripta as chaves Gemini de um row da tabela users."""
    return {
        "user_id":         row["user_id"],
        "first_name":      row.get("first_name"),
        "username":        row.get("username"),
        "gemini_free_key": decrypt_key(row["gemini_free_key"]) if row.get("gemini_free_key") else None,
        "gemini_paid_key": decrypt_key(row["gemini_paid_key"]) if row.get("gemini_paid_key") else None,
        "career_summary":  row.get("career_summary"),
        "career_vectors":  row.get("career_vectors"),
        "onboarding_step": row.get("onboarding_step"),
        "is_active":       row.get("is_active"),
    }


def get_user(user_id: int) -> dict | None:
    """Fetch user row by PK."""
    result = (
        get_client()
        .table("users")
        .select(
            "user_id, first_name, username, gemini_free_key, gemini_paid_key, "
            "career_summary, career_vectors, onboarding_step, is_active"
        )
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return _decrypt_user(result.data[0])


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


def set_user_keys(user_id: int, free_key: str, paid_key: str | None = None):
    """Encripta e salva as chaves Gemini do usuário."""
    enc_free = encrypt_key(free_key)
    enc_paid = encrypt_key(paid_key) if paid_key else None

    # Busca o step atual para preservar a lógica do CASE WHEN
    current = get_user(user_id)
    current_step = current.get("onboarding_step", "new") if current else "new"
    new_step = "keys_set" if current_step == "new" else current_step

    get_client().table("users").update({
        "gemini_free_key": enc_free,
        "gemini_paid_key": enc_paid,
        "onboarding_step": new_step,
    }).eq("user_id", user_id).execute()


def set_career_profile(user_id: int, career_summary: str, career_vectors: dict):
    """Salva o resumo de carreira e os vetores de embedding."""
    get_client().table("users").update({
        "career_summary":  career_summary,
        "career_vectors":  json.dumps(career_vectors),
        "onboarding_step": "ready",
    }).eq("user_id", user_id).execute()


def get_active_users() -> list[dict]:
    """Retorna todos os usuários ativos com chaves. Usado pelo pipeline cron."""
    result = (
        get_client()
        .table("users")
        .select(
            "user_id, first_name, gemini_free_key, gemini_paid_key, "
            "career_summary, career_vectors"
        )
        .eq("is_active", True)
        .not_.is_("gemini_free_key", "null")
        .execute()
    )
    return [_decrypt_user(r) for r in result.data]
