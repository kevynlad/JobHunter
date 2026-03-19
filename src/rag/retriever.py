"""
=============================================================
🔍 RETRIEVER.PY — Career Profile Search & Job Matching (V2)
=============================================================

Previously: loaded ~420MB SentenceTransformer model + queried ChromaDB
Now: loads ~50KB JSON vector store + cosine similarity in pure Python
=============================================================
"""
import json
import os
import math
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Shared config
VECTOR_STORE_PATH = Path(__file__).parent.parent.parent / "data" / "career_vectors.json"
EMBEDDING_MODEL = "text-embedding-004"

# Cache in memory after first load
_vector_store: dict | None = None


def _load_store() -> dict:
    """Load the JSON vector store (built by ingest.py). Cached in memory."""
    global _vector_store
    if _vector_store is None:
        if not VECTOR_STORE_PATH.exists():
            raise FileNotFoundError(
                f"Vector store not found at {VECTOR_STORE_PATH}.\n"
                "Run build_vector_db() to create it."
            )
        _vector_store = json.loads(VECTOR_STORE_PATH.read_text(encoding="utf-8"))
    return _vector_store


def _embed_query(text: str) -> list[float]:
    """Embed a single query text using Gemini API (free key)."""
    from google import genai
    from src.bot.key_router import get_key
    client = genai.Client(api_key=get_key("free"))
    result = client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
    return result.embeddings[0].values


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure Python cosine similarity. No numpy needed."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def query(text: str, k: int = 15) -> list[dict]:
    """
    Search the career vector store for chunks matching the query text.

    Returns list of dicts with: text, source, similarity (0-1, higher = better)
    """
    store = _load_store()
    query_emb = _embed_query(text)

    scored = []
    for i, (chunk, meta, emb) in enumerate(zip(
        store["chunks"], store["metadatas"], store["embeddings"]
    )):
        sim = _cosine_similarity(query_emb, emb)
        scored.append({
            "text": chunk,
            "source": meta.get("source", "unknown"),
            "similarity": sim,
            "distance": 1.0 - sim,  # backward compat with old API
        })

    # Sort by similarity descending
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:k]


def score_job(job_description: str) -> dict:
    """
    📊 Score how well a job description matches the user's career profile.

    Returns:
        score: 0-100 match percentage
        top_matches: most relevant career chunks
        interpretation: human-friendly label
    """
    try:
        matches = query(job_description[:3000], k=15)
    except FileNotFoundError:
        # Vector store not built yet — return neutral score instead of crashing
        return {"score": 50, "top_matches": [], "interpretation": "⚪ RAG não disponível"}

    if not matches:
        return {"score": 0, "top_matches": [], "interpretation": "🔴 Sem dados de carreira"}

    # Weighted average of top similarities (top match weighted 3x)
    sims = [m["similarity"] for m in matches]
    weights = [3, 2.5, 2, 1.5, 1] + [0.5] * max(0, len(sims) - 5)
    weights = weights[:len(sims)]
    weighted_avg = sum(s * w for s, w in zip(sims, weights)) / sum(weights)

    score = round(max(0, min(100, weighted_avg * 100)), 1)

    if score >= 80:
        interpretation = "🟢 Excelente fit!"
    elif score >= 60:
        interpretation = "🟡 Bom fit — vale aplicar"
    elif score >= 40:
        interpretation = "🟠 Fit parcial — avalie com cuidado"
    else:
        interpretation = "🔴 Fit fraco"

    return {
        "score": score,
        "top_matches": matches[:5],
        "interpretation": interpretation,
    }


if __name__ == "__main__":
    result = score_job("Analista de Produto com SQL e experiência em operações")
    print(f"Score: {result['score']}% — {result['interpretation']}")
