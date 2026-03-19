"""
key_router.py -- Dual API Key Router

Routes Gemini API tasks to the right tier:

FREE KEY  -> batch/pipeline (high-volume, low-stakes)
  - Pipeline batch classification (~200 vagas x2/day)
  - learn_from_job extraction

PAID KEY  -> interactive/user-facing (low-volume, high-quality)
  - Chat conversations
  - Cover letter / CV generation
  - analyze_and_save_url (triggered by user)
"""
import os


def get_key(tier: str = "paid") -> str:
    """Return the correct Gemini API key for the given tier."""
    if tier == "paid":
        paid = os.getenv("GEMINI_PAID_API_KEY", "").strip()
        if paid:
            return paid

    if tier == "free":
        free = os.getenv("GEMINI_FREE_API_KEY", "").strip()
        if free:
            return free

    # Fallback: any key from the legacy pool
    pool = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", "")).strip()
    keys = [k.strip() for k in pool.split(",") if k.strip()]
    if keys:
        return keys[0]

    raise ValueError(
        "No Gemini API key found. Set GEMINI_FREE_API_KEY and GEMINI_PAID_API_KEY in your .env"
    )


def get_key_pool(tier: str = "free") -> list:
    """Return all keys for a tier. Used by classifier for key rotation."""
    if tier == "free":
        free_key = os.getenv("GEMINI_FREE_API_KEY", "").strip()
        if free_key:
            return [free_key]

    if tier == "paid":
        paid_key = os.getenv("GEMINI_PAID_API_KEY", "").strip()
        if paid_key:
            return [paid_key]

    # Fallback: full legacy pool
    pool = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", "")).strip()
    keys = [k.strip() for k in pool.split(",") if k.strip()]
    return keys if keys else []
