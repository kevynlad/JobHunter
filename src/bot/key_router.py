"""
src/bot/key_router.py
━━━━━━━━━━━━━━━━━━━━
Multi-tenant Gemini API key router.

Priority (per user):
  1. User's own key from DB (BYOK)
  2. System fallback from env vars (for admin/pipeline use only)

Tiers:
  free  → embeddings, batch classification
  paid  → chat, cover letters, CV generation
"""
import os
import logging

logger = logging.getLogger(__name__)


def get_key(tier: str = "paid", user_id: int | None = None) -> str:
    """
    Return the Gemini API key for the given tier and user.

    If user_id is provided, fetches the user's own BYOK key from the DB.
    Falls back to system env vars if user has no key configured.
    """
    if user_id is not None:
        try:
            from src.db.users import get_user
            user = get_user(user_id)
            if user:
                if tier == "paid" and user.get("gemini_paid_key"):
                    return user["gemini_paid_key"]
                if tier == "free" and user.get("gemini_free_key"):
                    return user["gemini_free_key"]
                # Fallback: use free key for paid tier if no paid key
                if user.get("gemini_free_key"):
                    logger.info(f"user {user_id}: no {tier} key, falling back to free key")
                    return user["gemini_free_key"]
        except Exception as e:
            logger.warning(f"Could not fetch key for user {user_id}: {e}. Using system key.")

    # System fallback (admin / pipeline / local dev)
    return _get_system_key(tier)


def _get_system_key(tier: str) -> str:
    """Read system-level API key from env vars (admin/pipeline use only)."""
    if tier == "paid":
        key = os.getenv("GEMINI_PAID_API_KEY", "").strip()
        if key:
            return key

    if tier == "free":
        key = os.getenv("GEMINI_FREE_API_KEY", "").strip()
        if key:
            return key

    # Legacy pool fallback
    pool = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", "")).strip()
    keys = [k.strip() for k in pool.split(",") if k.strip()]
    if keys:
        return keys[0]

    raise ValueError(
        f"No Gemini API key found for tier='{tier}'. "
        "Set GEMINI_FREE_API_KEY / GEMINI_PAID_API_KEY in env, "
        "or ensure user has configured their BYOK key."
    )


def get_key_pool(tier: str = "free", user_id: int | None = None) -> list[str]:
    """Return all keys for a tier. Falls back gracefully."""
    try:
        key = get_key(tier, user_id)
        return [key] if key else []
    except ValueError:
        return []
