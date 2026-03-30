"""
src/db/users.py
━━━━━━━━━━━━━━
User CRUD + BYOK key encryption/decryption.
"""

import os
import logging
from cryptography.fernet import Fernet

from src.db.connection import get_conn

logger = logging.getLogger(__name__)

# MASTER_KEY lives only in Vercel/GitHub Actions env vars — never in the DB
_cipher = Fernet(os.environ["ENCRYPTION_MASTER_KEY"].encode())


def encrypt_key(raw: str) -> str:
    return _cipher.encrypt(raw.encode()).decode()


def decrypt_key(encrypted: str) -> str:
    return _cipher.decrypt(encrypted.encode()).decode()


def get_user(user_id: int) -> dict | None:
    """Fetch user row (no RLS needed — admin query by PK)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, first_name, username, gemini_free_key, gemini_paid_key, "
                "career_summary, career_vectors, onboarding_step, is_active "
                "FROM users WHERE user_id = %s",
                (user_id,)
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "user_id":        row[0],
        "first_name":     row[1],
        "username":       row[2],
        "gemini_free_key":  decrypt_key(row[3]) if row[3] else None,
        "gemini_paid_key":  decrypt_key(row[4]) if row[4] else None,
        "career_summary": row[5],
        "career_vectors": row[6],
        "onboarding_step": row[7],
        "is_active":      row[8],
    }


def upsert_user(user_id: int, first_name: str, username: str | None = None) -> dict:
    """Create user if not exists. Returns the user row."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, first_name, username)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    username   = EXCLUDED.username
                RETURNING user_id, onboarding_step
            """, (user_id, first_name, username))
            row = cur.fetchone()
    return {"user_id": row[0], "onboarding_step": row[1]}


def set_user_keys(user_id: int, free_key: str, paid_key: str | None = None):
    """Encrypt and store Gemini API keys."""
    enc_free = encrypt_key(free_key)
    enc_paid = encrypt_key(paid_key) if paid_key else None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET gemini_free_key = %s,
                    gemini_paid_key = %s,
                    onboarding_step = CASE
                        WHEN onboarding_step = 'new' THEN 'keys_set'
                        ELSE onboarding_step
                    END
                WHERE user_id = %s
            """, (enc_free, enc_paid, user_id))


def set_career_profile(user_id: int, career_summary: str, career_vectors: dict):
    """Save career summary text and embedding vectors."""
    import json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET career_summary  = %s,
                    career_vectors  = %s,
                    onboarding_step = 'ready'
                WHERE user_id = %s
            """, (career_summary, json.dumps(career_vectors), user_id))


def get_active_users() -> list[dict]:
    """Return all active users with their API keys. Used by cron pipeline."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, first_name, gemini_free_key, gemini_paid_key, "
                "career_summary, career_vectors "
                "FROM users WHERE is_active = TRUE AND gemini_free_key IS NOT NULL"
            )
            rows = cur.fetchall()
    return [
        {
            "user_id":       r[0],
            "first_name":    r[1],
            "gemini_free_key":  decrypt_key(r[2]) if r[2] else None,
            "gemini_paid_key":  decrypt_key(r[3]) if r[3] else None,
            "career_summary": r[4],
            "career_vectors": r[5],
        }
        for r in rows
    ]
