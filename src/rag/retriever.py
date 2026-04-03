"""
=============================================================
🔍 RETRIEVER.PY — Career Profile Search & Job Matching (V3)
=============================================================

Multi-tenant rewrite:
- Career vectors are ALWAYS loaded from the database (users.career_vectors)
- user_id is mandatory for all scoring functions
- Local file (career_vectors.json) is only used for local dev fallback
  when user_id is explicitly None (e.g. standalone CLI tests)
=============================================================
"""
import json
import os
import math
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

EMBEDDING_MODEL = "gemini-embedding-2"
BATCH_SIZE = 80
BATCH_DELAY_SECONDS = 80
MAX_RETRIES = 3

# Local file only used as fallback during local development (user_id=None)
_LOCAL_VECTOR_STORE_PATH = Path(__file__).parent.parent.parent / "data" / "career_vectors.json"

# Per-user in-memory cache: {user_id: store_dict}
_store_cache: dict[int, dict] = {}


# ─────────────────────────────────────────────────────────────
# Internal: Vector Store Loading
# ─────────────────────────────────────────────────────────────

def _load_store_for_user(user_id: int) -> dict:
    """
    Load career vectors from the database for a specific user.
    Caches in memory per process run to avoid repeated DB calls.
    """
    if user_id in _store_cache:
        return _store_cache[user_id]

    logger.info(f"    📡 Loading career vectors from DB for user {user_id}...")
    try:
        from src.db.users import get_user
        user = get_user(user_id)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch user {user_id} from DB: {e}") from e

    if not user:
        raise RuntimeError(f"User {user_id} not found in database.")

    raw_vectors = user.get("career_vectors")
    if not raw_vectors:
        raise RuntimeError(
            f"User {user_id} has no career_vectors. "
            "User must complete onboarding and upload a career profile first."
        )

    # career_vectors may be stored as a JSON string or already a dict (JSONB)
    if isinstance(raw_vectors, str):
        store = json.loads(raw_vectors)
    else:
        store = raw_vectors

    if not store.get("chunks") or not store.get("embeddings"):
        raise RuntimeError(
            f"User {user_id} career_vectors is malformed (missing chunks or embeddings). "
            "Re-run the onboarding career profile upload."
        )

    logger.info(f"    ✅ Loaded {len(store['chunks'])} career chunks for user {user_id}.")
    _store_cache[user_id] = store
    return store


def _load_store_local() -> dict:
    """Fallback: load from local JSON file. Only for local dev without user_id."""
    if not _LOCAL_VECTOR_STORE_PATH.exists():
        raise FileNotFoundError(
            f"Local vector store not found at {_LOCAL_VECTOR_STORE_PATH}.\n"
            "Either provide a user_id (multi-tenant) or run build_vector_db() to create it."
        )
    return json.loads(_LOCAL_VECTOR_STORE_PATH.read_text(encoding="utf-8"))


def _get_store(user_id: int | None) -> dict:
    """Route to correct vector store: DB (multi-tenant) or local (dev only)."""
    if user_id is not None:
        return _load_store_for_user(user_id)
    return _load_store_local()


# ─────────────────────────────────────────────────────────────
# Internal: Embedding
# ─────────────────────────────────────────────────────────────

def _embed_query(text: str, user_id: int | None = None) -> list[float]:
    """Embed a single query text using Gemini API."""
    from google import genai
    from src.bot.key_router import get_key

    api_key = get_key("free", user_id=user_id)
    client = genai.Client(api_key=api_key)

    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    return result.embeddings[0].values


def _embed_batch(texts: list[str], user_id: int | None = None) -> list[list[float]]:
    """Embed a list of texts using Gemini API in batches of 80 with 80s delay between batches.

    Each item in a batch counts as 1 request against the 100 RPM free tier limit.
    With BATCH_SIZE=80 and 80s delay, we stay safely under the limit.
    """
    from google import genai
    from google.genai import errors as genai_errors
    from src.bot.key_router import get_key

    api_key = get_key("free", user_id=user_id)
    client = genai.Client(api_key=api_key)

    all_embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = math.ceil(len(texts) / BATCH_SIZE)
        logger.info(f"    📦 Embedding batch {batch_num}/{total_batches} ({len(batch)} items)...")

        for attempt in range(MAX_RETRIES):
            try:
                result = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=batch,
                )
                for item in result.embeddings:
                    all_embeddings.append(item.values)
                break
            except genai_errors.ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    retry_after = 90
                    if hasattr(e, 'message') and "retry in" in str(e.message).lower():
                        import re
                        match = re.search(r"retry in ([\d.]+)s", str(e.message), re.IGNORECASE)
                        if match:
                            retry_after = float(match.group(1)) + 5
                    logger.warning(f"    ⏳ Rate limit hit, waiting {retry_after:.0f}s (attempt {attempt+1}/{MAX_RETRIES})...")
                    time.sleep(retry_after)
                else:
                    raise
            except Exception:
                if attempt < MAX_RETRIES - 1:
                    wait = 10 * (attempt + 1)
                    logger.warning(f"    ⚠️ Embedding error, retrying in {wait}s ({attempt+1}/{MAX_RETRIES})...")
                    time.sleep(wait)
                else:
                    raise

        if i + BATCH_SIZE < len(texts):
            logger.info(f"    ⏳ Waiting {BATCH_DELAY_SECONDS}s before next batch...")
            time.sleep(BATCH_DELAY_SECONDS)

    return all_embeddings


# ─────────────────────────────────────────────────────────────
# Internal: Similarity
# ─────────────────────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure Python cosine similarity. No numpy needed."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _calc_score(similarities: list[float]) -> tuple[float, str]:
    """Calculate weighted score and interpretation from a list of similarity values."""
    if not similarities:
        return 0.0, "🔴 Sem dados de carreira"

    similarities = sorted(similarities, reverse=True)
    top_sims = similarities[:15]
    weights = [3, 2.5, 2, 1.5, 1] + [0.5] * max(0, len(top_sims) - 5)
    weights = weights[:len(top_sims)]
    weighted_avg = sum(s * w for s, w in zip(top_sims, weights)) / sum(weights)
    score = round(max(0, min(100, weighted_avg * 100)), 1)

    if score >= 80:
        interp = "🟢 Excelente fit!"
    elif score >= 60:
        interp = "🟡 Bom fit — vale aplicar"
    elif score >= 40:
        interp = "🟠 Fit parcial — avalie com cuidado"
    else:
        interp = "🔴 Fit fraco"

    return score, interp


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def query(text: str, k: int = 15, user_id: int | None = None) -> list[dict]:
    """
    Search the career vector store for chunks matching the query text.
    Returns list of dicts with: text, source, similarity (0-1, higher = better)
    """
    store = _get_store(user_id)
    query_emb = _embed_query(text, user_id=user_id)

    scored = []
    for chunk, meta, emb in zip(store["chunks"], store["metadatas"], store["embeddings"]):
        sim = _cosine_similarity(query_emb, emb)
        scored.append({
            "text": chunk,
            "source": meta.get("source", "unknown"),
            "similarity": sim,
            "distance": 1.0 - sim,
        })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:k]


def score_job(job_description: str, user_id: int | None = None) -> dict:
    """
    Score how well a job description matches the user's career profile.

    Args:
        job_description: Raw text of the job posting.
        user_id: Required for multi-tenant. Fetches vectors from DB.

    Returns:
        score: 0-100 match percentage
        top_matches: most relevant career chunks
        interpretation: human-friendly label
    """
    try:
        matches = query(job_description[:3000], k=15, user_id=user_id)
    except (FileNotFoundError, RuntimeError) as e:
        logger.warning(f"RAG unavailable: {e}")
        return {"score": 50, "top_matches": [], "interpretation": "⚪ RAG não disponível"}

    if not matches:
        return {"score": 0, "top_matches": [], "interpretation": "🔴 Sem dados de carreira"}

    score, interp = _calc_score([m["similarity"] for m in matches])
    return {
        "score": score,
        "top_matches": matches[:5],
        "interpretation": interp,
    }


def score_jobs_batch(jobs_data: list[dict], user_id: int | None = None) -> list[dict]:
    """
    Efficiently score a LARGE list of jobs against the user's career profile.
    Uses batch embeddings to reduce API calls by 100x.

    Args:
        jobs_data: List of dicts with {"id": str, "text": str}
        user_id:   Required for multi-tenant. Fetches vectors from DB.

    Returns:
        List of dicts with {"id": str, "score": float, "interpretation": str}
    """
    if not jobs_data:
        return []

    texts = [j["text"][:3000] for j in jobs_data]

    # 1. Batch Embed all job texts
    logger.info(f"    📡 Requesting batch embeddings for {len(texts)} jobs (user={user_id})...")
    try:
        job_embeddings = _embed_batch(texts, user_id=user_id)
    except Exception as e:
        logger.error(f"    ❌ Batch embedding error: {e}")
        return [{"id": j["id"], "score": 50, "interpretation": "⚪ RAG Error Fallback"} for j in jobs_data]

    if len(job_embeddings) != len(texts):
        logger.error(f"    ❌ Mismatch: requested {len(texts)} embeddings, got {len(job_embeddings)}")
        return [{"id": j["id"], "score": 50, "interpretation": "⚪ RAG Mismatch Fallback"} for j in jobs_data]

    # 2. Load career vectors for this user
    try:
        store = _get_store(user_id)
    except (FileNotFoundError, RuntimeError) as e:
        logger.error(f"    ❌ Could not load career store for user {user_id}: {e}")
        return [{"id": j["id"], "score": 50, "interpretation": "⚪ RAG Store Error"} for j in jobs_data]

    career_embeddings = store["embeddings"]

    # 3. Score each job
    results = []
    for i, job_emb in enumerate(job_embeddings):
        similarities = [_cosine_similarity(job_emb, c_emb) for c_emb in career_embeddings]
        score, interp = _calc_score(similarities)
        results.append({
            "id": jobs_data[i]["id"],
            "score": score,
            "interpretation": interp,
        })

    return results


if __name__ == "__main__":
    # Local dev test — requires career_vectors.json in data/
    result = score_job("Analista de Produto com SQL e experiência em operações")
    print(f"Score: {result['score']}% — {result['interpretation']}")
