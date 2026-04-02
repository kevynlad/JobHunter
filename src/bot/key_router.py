"""
src/bot/key_router.py
━━━━━━━━━━━━━━━━━━━━
Multi-tenant Gemini API key router.

BYOK STRICT MODE:
  - If user_id is given, ONLY user keys from DB are returned.
  - System keys (env vars) are ONLY used when user_id is None.
  - If an established user has no key, raise KeyError with a clear message.
    The pipeline must catch this and notify the user via Telegram.

Tiers:
  free  → embeddings (RAG), cheap batch inference
  paid  → LLM job classification, chat, CV/cover letter generation
"""
import os
import logging

logger = logging.getLogger(__name__)


class MissingUserKeyError(ValueError):
    """Raised when an established user has not configured a required API key."""
    def __init__(self, user_id: int, tier: str):
        self.user_id = user_id
        self.tier = tier
        msg = (
            f"Usuário {user_id} não tem chave '{tier}' configurada. "
            "Configure sua chave pelo bot (ex.: 'Minha chave é AIza...')"
        )
        super().__init__(msg)


def get_key(tier: str = "paid", user_id: int | None = None) -> str:
    """
    Return the Gemini API key for the given tier and user.

    BYOK STRICT MODE:
      - user_id provided → ONLY use keys from the database.
      - user_id is None  → use system env vars (pipeline admin / local dev only).

    Raises:
      MissingUserKeyError: if user_id is given but the requested key is not set.
      ValueError:          if no system key is found (user_id is None).
    """
    if user_id is not None:
        try:
            from src.db.users import get_user
            user = get_user(user_id)
        except Exception as e:
            logger.error(f"Failed to fetch user {user_id} from DB: {e}")
            raise MissingUserKeyError(user_id, tier) from e

        if not user:
            raise MissingUserKeyError(user_id, tier)

        if tier == "paid":
            key = user.get("gemini_paid_key")
            if key:
                return key
            # If no paid key, fall back to free key (with penalty applied in pipeline)
            free_key = user.get("gemini_free_key")
            if free_key:
                logger.warning(
                    f"User {user_id}: no paid key configured. "
                    "Returning free key — pipeline should apply job limit penalty."
                )
                return free_key
            raise MissingUserKeyError(user_id, "free or paid")

        if tier == "free":
            key = user.get("gemini_free_key")
            if key:
                return key
            raise MissingUserKeyError(user_id, "free")

        raise ValueError(f"Unknown tier: '{tier}'. Use 'free' or 'paid'.")

    # No user_id → system context (admin scripts, local dev, initial bot contact)
    return _get_system_key(tier)


def get_key_pool(tier: str = "free", user_id: int | None = None) -> list[str]:
    """
    Return a list of keys for the given tier.
    Returns an empty list if no key is available (do NOT raise).
    Used by the classifier's pool-rotation logic.
    """
    try:
        key = get_key(tier, user_id)
        return [key] if key else []
    except (MissingUserKeyError, ValueError):
        return []


def user_has_paid_key(user_id: int) -> bool:
    """
    Returns True if the user has a dedicated paid key configured.
    Used by the pipeline to decide whether to apply the job-limit penalty.
    """
    try:
        from src.db.users import get_user
        user = get_user(user_id)
        return bool(user and user.get("gemini_paid_key"))
    except Exception:
        return False


def _get_system_key(tier: str) -> str:
    """
    Read system-level API key from env vars.
    ONLY for: admin scripts, local development, initial bot contact (onboarding).
    NEVER called when a user_id is available in the pipeline.
    """
    if tier == "paid":
        key = os.getenv("GEMINI_PAID_API_KEY", "").strip()
        if key:
            return key

    if tier == "free":
        key = os.getenv("GEMINI_FREE_API_KEY", "").strip()
        if key:
            return key

    raise ValueError(
        f"No system Gemini API key found for tier='{tier}'. "
        "Set GEMINI_FREE_API_KEY / GEMINI_PAID_API_KEY in env vars."
    )
