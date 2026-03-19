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
EMBEDDING_MODEL = "gemini-embedding-001"

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
    """Embed a single query text using Gemini API (free key) via official SDK."""
    from google import genai
    from src.bot.key_router import get_key
    
    api_key = get_key("free")
    client = genai.Client(api_key=api_key)
    
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    return result.embeddings[0].values


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using Gemini API in batches of 100."""
    from google import genai
    from src.bot.key_router import get_key
    
    api_key = get_key("free")
    client = genai.Client(api_key=api_key)
    
    all_embeddings = []
    BATCH_SIZE = 100
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=batch,
        )
        for item in result.embeddings:
            all_embeddings.append(item.values)
    return all_embeddings


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


def score_jobs_batch(jobs_data: list[dict]) -> list[dict]:
    """
    📊 Efficiently score a LARGE list of jobs against your career profile.
    Uses batch embeddings to reduce API calls by 100x.
    
    Args:
        jobs_data: List of dicts with {"id": str, "text": str}
        
    Returns:
        List of dicts with {"id": str, "score": float, "interpretation": str, "top_matches": list}
    """
    if not jobs_data:
        return []

    texts = [j["text"][:3000] for j in jobs_data]
    
    # 1. Batch Embed all job texts
    print(f"    📡 Requesting batch embeddings for {len(texts)} jobs...")
    try:
        job_embeddings = _embed_batch(texts)
    except Exception as e:
        print(f"    [!] Batch RAG error: {e}. Falling back to default scores.")
        return [{"id": j["id"], "score": 50, "interpretation": "⚪ RAG Error Fallback"} for j in jobs_data]

    # 2. Load career vectors
    try:
        store = _load_store()
    except FileNotFoundError:
        return [{"id": j["id"], "score": 50, "interpretation": "⚪ RAG Store not found"} for j in jobs_data]

    career_embeddings = [chunk["embedding"] for chunk in store["chunks"]]

    # 3. Calculate scores for each job (pure Python, but local math is fast)
    results = []
    for i, job_emb in enumerate(job_embeddings):
        # Calculate similarity with all career chunks
        similarities = []
        for career_emb in career_embeddings:
            sim = _cosine_similarity(job_emb, career_emb)
            similarities.append(sim)
        
        # Calculate weighted match score (same logic as score_job)
        similarities.sort(reverse=True)
        top_sims = similarities[:15]
        
        # Weighted average (top match weighted 3x)
        weights = [3, 2.5, 2, 1.5, 1] + [0.5] * max(0, len(top_sims) - 5)
        weights = weights[:len(top_sims)]
        weighted_avg = sum(s * w for s, w in zip(top_sims, weights)) / sum(weights)
        
        score = round(max(0, min(100, weighted_avg * 100)), 1)
        
        # Interpretation
        if score >= 80: interpretation = "🟢 Excelente fit!"
        elif score >= 60: interpretation = "🟡 Bom fit — vale aplicar"
        elif score >= 40: interpretation = "🟠 Fit parcial — avalie com cuidado"
        else: interpretation = "🔴 Fit fraco"
        
        results.append({
            "id": jobs_data[i]["id"],
            "score": score,
            "interpretation": interpretation
        })
        
    return results


if __name__ == "__main__":
    result = score_job("Analista de Produto com SQL e experiência em operações")
    print(f"Score: {result['score']}% — {result['interpretation']}")
