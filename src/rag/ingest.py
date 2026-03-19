"""
=============================================================
📄 INGEST.PY — Career Document Ingestion (V2 - Gemini Embedding)
=============================================================

Previously used: sentence-transformers (~420MB local model) + ChromaDB (~100MB)
Now uses: Gemini embedding-001 API + lightweight JSON vector store (~50KB)

Railway storage savings: ~520MB → ~50KB (99.99% reduction)
Cost: ~$0.00015/1K tokens × ~5K tokens (career docs) = ~$0.0007 per rebuild (negligible)
=============================================================
"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# pypdf: reads PDF files
from pypdf import PdfReader

# docx: reads Word (.docx) files
from docx import Document as DocxDocument

load_dotenv()

# ----- CONFIGURATION -----

# Career document directory
CAREER_DOCS_PATH = Path(__file__).parent.parent.parent / "data" / "career"

# Vector store: a simple JSON file replacing ChromaDB entirely
VECTOR_STORE_PATH = Path(__file__).parent.parent.parent / "data" / "career_vectors.json"

# Gemini embedding model
EMBEDDING_MODEL = "gemini-embedding-001"

# Chunk size (in characters)
CHUNK_SIZE = 500
CHUNK_OVERLAP = 150


# ----- DOCUMENT READERS -----

def read_pdf(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def read_docx(file_path: Path) -> str:
    doc = DocxDocument(str(file_path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def read_document(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return read_pdf(file_path)
    elif ext == ".docx":
        return read_docx(file_path)
    elif ext in (".md", ".txt"):
        return file_path.read_text(encoding="utf-8")
    return ""


def split_into_chunks(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start:start + CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ----- GEMINI EMBEDDING -----

def _embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Call Gemini's embedding API for a list of texts using the official SDK.
    Uses 'gemini-embedding-001' which avoids the v1beta NOT_FOUND issues.
    """
    from google import genai
    from src.bot.key_router import get_key

    api_key = get_key("free")
    client = genai.Client(api_key=api_key)

    embeddings = []
    # Send in batches of 100 to stay within limits
    BATCH_SIZE = 100
    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch = texts[batch_start:batch_start + BATCH_SIZE]
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=batch,
        )
        for item in result.embeddings:
            embeddings.append(item.values)
    return embeddings



# ----- MAIN INGEST FUNCTION -----

def build_vector_db() -> dict:
    """
    🚀 Build the career vector store using Gemini embeddings.

    Replaces ChromaDB + sentence-transformers with:
    - Gemini gemini-embedding-001 API (online, no local model)
    - Simple JSON file as vector store (~50KB instead of ~520MB)

    Returns a summary dict.
    """
    CAREER_DOCS_PATH.mkdir(parents=True, exist_ok=True)

    supported = {".pdf", ".docx", ".md", ".txt"}
    doc_files = [f for f in CAREER_DOCS_PATH.iterdir() if f.is_file() and f.suffix.lower() in supported]

    all_chunks = []
    all_meta = []

    if not doc_files:
        # Fallback: read career profile from Railway environment variables
        # This handles the case where the Volume is empty (no physical files)
        master = os.getenv("MASTER_PROFILE", "").strip()
        product_ops = os.getenv("PRODUCT_OPS_PROFILE", "").strip()

        env_texts = [(master, "MASTER_PROFILE"), (product_ops, "PRODUCT_OPS_PROFILE")]
        env_texts = [(t, src) for t, src in env_texts if t]

        if env_texts:
            print(f"📂 No files in {CAREER_DOCS_PATH} — using env vars as career corpus.")
            for text, source in env_texts:
                chunks = split_into_chunks(text)
                print(f"  📋 {source} → {len(chunks)} chunks")
                for i, chunk in enumerate(chunks):
                    all_chunks.append(chunk)
                    all_meta.append({"source": source, "chunk_idx": i})
        else:
            print(f"[!] No career documents and no MASTER_PROFILE env var found.")
            return {"status": "error", "message": "No career data — add files to data/career/ or set MASTER_PROFILE env var"}
    else:
        print(f"📂 Found {len(doc_files)} career document(s). Building Gemini vector store...")
        for doc_file in doc_files:
            print(f"  📄 {doc_file.name}")
            text = read_document(doc_file)
            if not text:
                continue
            chunks = split_into_chunks(text)
            print(f"     → {len(chunks)} chunks")
            for i, chunk in enumerate(chunks):
                all_chunks.append(chunk)
                all_meta.append({"source": doc_file.name, "chunk_idx": i})

    if not all_chunks:
        return {"status": "error", "message": "No text extracted from documents"}

    print(f"\n🧠 Embedding {len(all_chunks)} chunks via Gemini API (gemini-embedding-001)...")
    embeddings = _embed_texts(all_chunks)

    # Save to lightweight JSON (replaces ChromaDB entirely)
    vector_store = {
        "chunks": all_chunks,
        "metadatas": all_meta,
        "embeddings": embeddings,
        "model": EMBEDDING_MODEL,
    }
    VECTOR_STORE_PATH.write_text(json.dumps(vector_store), encoding="utf-8")

    size_kb = VECTOR_STORE_PATH.stat().st_size / 1024
    print(f"\n✅ Vector store saved to {VECTOR_STORE_PATH} ({size_kb:.1f} KB)")
    print(f"   (Replaced ~520MB ChromaDB + model with {size_kb:.1f} KB JSON)")

    return {
        "status": "success",
        "documents": len(doc_files),
        "chunks": len(all_chunks),
        "vector_store_kb": round(size_kb, 1),
    }


# Legacy alias for backward compatibility with original ingest.py callers
def ingest_documents() -> dict:
    return build_vector_db()


if __name__ == "__main__":
    result = build_vector_db()
    print(f"\nResult: {result}")
