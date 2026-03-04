"""
=============================================================
🔍 RETRIEVER.PY — Career Profile Search & Job Matching
=============================================================

WHAT DOES THIS FILE DO?
-----------------------
After ingest.py stored your career in the database, this file
lets you SEARCH it. It answers two key questions:

1. query()     → "What parts of my career match this text?"
2. score_job() → "How well does this job match my profile?" (0-100)

HOW DOES SEARCH WORK?
---------------------
Remember: each chunk of your career is stored as a list of numbers
(an embedding). When you search:

1. Your search text is ALSO converted into numbers (embedding)
2. We compare those numbers against ALL stored chunks
3. The chunks with the MOST SIMILAR numbers are returned

This is called "semantic search" — it finds meaning, not keywords.

Example:
  Your resume says: "Built REST APIs using FastAPI and PostgreSQL"
  A job asks for: "Experience with backend web development"
  → These will match even though they share no exact words!
  Because the MEANING (embeddings) is similar.

=============================================================
"""

import sys
from pathlib import Path

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import chromadb
from sentence_transformers import SentenceTransformer

from src.rag.ingest import CHROMA_DB_PATH, COLLECTION_NAME, EMBEDDING_MODEL_NAME


# We'll load these once and reuse them (loading is slow, reusing is fast)
_model = None
_collection = None


def _get_model() -> SentenceTransformer:
    """
    Load the embedding model (only once).
    
    We use a "singleton" pattern here — the first time you call this,
    it loads the model. Every time after that, it returns the same model.
    This avoids loading the ~80MB model repeatedly.
    """
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def _get_collection() -> chromadb.Collection:
    """
    Connect to the ChromaDB collection (only once).
    
    This opens the database that ingest.py created and gets
    the "career_profile" collection where your chunks are stored.
    """
    global _collection
    if _collection is None:
        if not CHROMA_DB_PATH.exists():
            raise FileNotFoundError(
                f"Database not found at {CHROMA_DB_PATH.resolve()}.\n"
                "Run 'jobhunter ingest' first to process your career documents."
            )
        client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection


def query(text: str, k: int = 15) -> list[dict]:
    """
    🔍 Search your career profile for chunks that match the given text.
    
    Args:
        text: What to search for (e.g. "Python web development experience")
        k:    How many results to return (default: top 15)
    
    Returns:
        A list of dicts, each containing:
        - "text":     The matching chunk text
        - "source":   Which file it came from
        - "distance": How different it is (LOWER = MORE similar)
    
    Example:
        results = query("machine learning experience", k=3)
        for r in results:
            print(f"From {r['source']}: {r['text'][:100]}...")
    """
    model = _get_model()
    collection = _get_collection()
    
    # Step 1: Convert the search text into an embedding
    query_embedding = model.encode([text])[0].tolist()
    
    # Step 2: Ask ChromaDB to find the most similar chunks
    # ChromaDB uses "distance" — lower distance = more similar
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(k, collection.count()),  # Don't ask for more than we have
    )
    
    # Step 3: Format the results into a clean list of dicts
    formatted_results = []
    
    for i in range(len(results["ids"][0])):
        formatted_results.append({
            "text": results["documents"][0][i],
            "source": results["metadatas"][0][i].get("source_file", "unknown"),
            "distance": results["distances"][0][i],
        })
    
    return formatted_results


def score_job(job_description: str) -> dict:
    """
    📊 Score how well a job description matches your career profile.
    
    This is the key function that tells you:
    "Is this job a good fit for me?"
    
    How it works:
    1. Search your career profile for chunks related to the job
    2. Look at the "distance" scores from ChromaDB
    3. Convert distances into a 0-100 match score
    
    The scoring math:
    - ChromaDB returns "distances" (0 = identical, 2 = completely different)
    - We average the distances of the top matches
    - Convert to a score: score = max(0, (1 - avg_distance) * 100)
    
    Args:
        job_description: The full text of the job posting
    
    Returns:
        A dict with:
        - "score":          0-100 match score
        - "top_matches":    The most relevant career chunks
        - "interpretation": A human-friendly label
    
    Example:
        result = score_job("Looking for a Python developer with ML experience...")
        print(f"Match: {result['score']}% — {result['interpretation']}")
    """
    # Get the top 15 most relevant career chunks
    matches = query(job_description, k=15)
    
    if not matches:
        return {
            "score": 0,
            "top_matches": [],
            "interpretation": "No career data found. Run 'jobhunter ingest' first.",
        }
    
    # Calculate average distance across top matches
    # We use the BEST (lowest) distances, weighted toward the top match
    distances = [match["distance"] for match in matches]
    
    # Use the best match more heavily (it matters most)
    # Weight: [3, 2.5, 2, 1.5, 1] then 0.5 for the remaining tail up to 15
    weights = [3, 2.5, 2, 1.5, 1] + [0.5] * (len(distances) - 5) if len(distances) > 5 else [3, 2, 1, 1, 1][:len(distances)]
    weighted_avg = sum(d * w for d, w in zip(distances, weights)) / sum(weights)
    
    # Convert distance to a 0-100 score
    # ChromaDB configured with cosine returns distance = 1 - cosine_similarity.
    # To get percentage score, we accurately map it: score = (1 - weighted_avg) * 100
    normalized_score = max(0, min(100, (1.0 - weighted_avg) * 100))
    score = round(normalized_score, 1)
    
    # Give a human-friendly interpretation
    if score >= 80:
        interpretation = "🟢 Excellent match!"
    elif score >= 60:
        interpretation = "🟡 Good match — worth applying"
    elif score >= 40:
        interpretation = "🟠 Partial match — review carefully"
    else:
        interpretation = "🔴 Weak match — probably not a fit"
    
    return {
        "score": score,
        "top_matches": matches,
        "interpretation": interpretation,
    }


# Quick test when running this file directly
if __name__ == "__main__":
    print("🔍 Testing retriever...")
    print("\n--- Querying for 'Python programming' ---")
    results = query("Python programming", k=3)
    for r in results:
        safe_text = r['text'][:150].replace('\n', ' ').encode('ascii', errors='replace').decode('ascii')
        print(f"\n  📎 From: {r['source']} (distance: {r['distance']:.3f})")
        print(f"     {safe_text}...")
    
    print("\n--- Scoring a sample job ---")
    sample_job = "We are looking for a Python developer with experience in data science and machine learning."
    result = score_job(sample_job)
    print(f"  Score: {result['score']}% — {result['interpretation']}")
