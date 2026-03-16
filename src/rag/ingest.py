"""
=============================================================
📄 INGEST.PY — Career Document Ingestion
=============================================================

WHAT DOES THIS FILE DO?
-----------------------
This is the first step of the RAG pipeline. "Ingest" means
"to take in and process". Here's what happens:

1. READ your career documents (resume PDF, cover letters, etc.)
2. SPLIT them into small pieces called "chunks"
3. CONVERT each chunk into numbers called "embeddings"
4. STORE everything in a local database (ChromaDB)

WHY DO WE SPLIT TEXT INTO CHUNKS?
---------------------------------
Imagine you have a 5-page resume. If we search the whole thing
at once, it's too broad. But if we split it into small paragraphs,
we can find the EXACT part that matches a job description.

WHAT ARE EMBEDDINGS?
--------------------
Computers don't understand words, they understand numbers.
An "embedding" converts text like "Python developer with 3 years
experience" into a list of ~384 numbers like [0.12, -0.45, 0.78, ...].

The magic is: SIMILAR texts get SIMILAR numbers.
So "Python developer" and "Software engineer using Python"
will have numbers that are very close to each other.

This lets us do "semantic search" — finding things by MEANING,
not just by exact words.

=============================================================
"""

import os
import sys
from pathlib import Path

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# chromadb: our local vector database (stores embeddings)
import chromadb

# sentence_transformers: creates embeddings locally on your machine (free!)
from sentence_transformers import SentenceTransformer

# pypdf: reads PDF files
from pypdf import PdfReader

# docx: reads Word (.docx) files
from docx import Document as DocxDocument


# ----- CONFIGURATION -----

# Where we store the ChromaDB database files
CHROMA_DB_PATH = Path(__file__).parent.parent.parent / "data" / "chroma_db"

# Where you put your career documents (resume, certificates, etc.)
CAREER_DOCS_PATH = Path(__file__).parent.parent.parent / "data" / "career"

# The embedding model we use. 
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# The name of our ChromaDB collection (like a "table" in a regular database)
COLLECTION_NAME = "career_profile"

# How big each text chunk should be (in characters)
CHUNK_SIZE = 500

# How much overlap between chunks (so we don't cut sentences in half)
CHUNK_OVERLAP = 150


def read_pdf(file_path: Path) -> str:
    """
    Read all text from a PDF file.
    
    How it works:
    - Opens the PDF
    - Goes through each page
    - Extracts the text from each page
    - Joins all pages into one big string
    """
    reader = PdfReader(str(file_path))
    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:  # Some pages might be empty (like images)
            text_parts.append(page_text)
    return "\n".join(text_parts)


def read_docx(file_path: Path) -> str:
    """
    Read all text from a Word (.docx) file.
    
    How it works:
    - Opens the .docx file
    - Goes through each paragraph
    - Joins all paragraphs into one string
    """
    doc = DocxDocument(str(file_path))
    text_parts = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():  # Skip empty paragraphs
            text_parts.append(paragraph.text)
    return "\n".join(text_parts)


def read_markdown(file_path: Path) -> str:
    """
    Read a Markdown (.md) or plain text (.txt) file.
    This is the simplest — just read the file as-is.
    """
    return file_path.read_text(encoding="utf-8")


def read_document(file_path: Path) -> str:
    """
    Read any supported document by checking its file extension.
    
    Supported formats:
    - .pdf  → uses read_pdf()
    - .docx → uses read_docx()
    - .md   → uses read_markdown()
    - .txt  → uses read_markdown()
    """
    extension = file_path.suffix.lower()  # e.g. ".pdf"
    
    if extension == ".pdf":
        return read_pdf(file_path)
    elif extension == ".docx":
        return read_docx(file_path)
    elif extension in (".md", ".txt"):
        return read_markdown(file_path)
    else:
        print(f"  ⚠️  Skipping unsupported file type: {file_path.name}")
        return ""


def split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split a long text into smaller overlapping pieces.
    
    Example with chunk_size=10, overlap=3:
    
    Text: "Hello world, this is a test of chunking"
    
    Chunk 1: "Hello worl"      (characters 0-9)
    Chunk 2: "orl, this "      (characters 7-16, overlaps 3 chars)
    Chunk 3: "his is a t"      (characters 14-23, overlaps 3 chars)
    ... and so on
    
    WHY OVERLAP?
    If a sentence falls right at a split point, the overlap
    ensures both chunks contain the full sentence.
    """
    if not text or len(text) == 0:
        return []
    
    chunks = []
    start = 0
    
    while start < len(text):
        # Take a slice of text from 'start' to 'start + chunk_size'
        end = start + chunk_size
        chunk = text[start:end]
        
        # Only add non-empty chunks
        if chunk.strip():
            chunks.append(chunk.strip())
        
        # Move forward by (chunk_size - overlap) characters
        # This creates the overlap between consecutive chunks
        start += chunk_size - overlap
    
    return chunks


def ingest_documents() -> dict:
    """
    🚀 MAIN FUNCTION — Run the full ingestion pipeline.
    
    This is what happens when you run: jobhunter ingest
    
    Steps:
    1. Find all documents in data/career/
    2. Read each document
    3. Split into chunks
    4. Create embeddings for each chunk
    5. Store everything in ChromaDB
    
    Returns a summary dict with stats about what was ingested.
    """
    
    # --- Step 0: Make sure the folders exist ---
    CAREER_DOCS_PATH.mkdir(parents=True, exist_ok=True)
    CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)
    
    # --- Step 1: Find all documents ---
    supported_extensions = {".pdf", ".docx", ".md", ".txt"}
    doc_files = [
        f for f in CAREER_DOCS_PATH.iterdir()     # List all files in the folder
        if f.is_file()                              # Only files (not folders)
        and f.suffix.lower() in supported_extensions # Only supported types
    ]
    
    if not doc_files:
        return {
            "status": "error",
            "message": f"No documents found! Please put your resume and career docs in:\n{CAREER_DOCS_PATH.resolve()}"
        }
    
    print(f"📂 Found {len(doc_files)} document(s) in {CAREER_DOCS_PATH.resolve()}")
    
    # --- Step 2 & 3: Read and chunk each document ---
    all_chunks = []      # The text chunks
    all_metadatas = []   # Info about each chunk (which file it came from)
    all_ids = []         # Unique ID for each chunk
    
    chunk_counter = 0
    
    for doc_file in doc_files:
        print(f"  📄 Reading: {doc_file.name}")
        
        text = read_document(doc_file)
        if not text:
            continue
        
        chunks = split_into_chunks(text)
        print(f"     → Split into {len(chunks)} chunks")
        
        for chunk in chunks:
            all_chunks.append(chunk)
            all_metadatas.append({
                "source_file": doc_file.name,  # Remember which file this came from
                "chunk_index": chunk_counter,
            })
            all_ids.append(f"chunk_{chunk_counter}")
            chunk_counter += 1
    
    if not all_chunks:
        return {
            "status": "error",
            "message": "Documents were found but no text could be extracted from them."
        }
    
    # --- Step 4: Create embeddings ---
    print(f"\n🧠 Loading embedding model: {EMBEDDING_MODEL_NAME}")
    print("   (This may take a minute the first time — it downloads ~80MB)")
    
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    
    print(f"   Creating embeddings for {len(all_chunks)} chunks...")
    # This converts each text chunk into a list of numbers (the embedding)
    embeddings = model.encode(all_chunks, show_progress_bar=True)
    # Convert numpy arrays to plain Python lists (ChromaDB needs this)
    embeddings_list = [embedding.tolist() for embedding in embeddings]
    
    # --- Step 5: Store in ChromaDB ---
    print(f"\n💾 Saving to ChromaDB at: {CHROMA_DB_PATH.resolve()}")
    
    # Create (or connect to) the database
    client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    
    # Delete old collection if it exists (fresh start)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # Collection didn't exist yet, that's fine
    
    # Create a new collection and add all our data
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={
            "description": "Career profile embeddings for job matching",
            "hnsw:space": "cosine"  # Forces cosine similarity computation
        }
    )
    
    collection.add(
        ids=all_ids,               # Unique identifier for each chunk
        documents=all_chunks,      # The original text (stored for reference)
        embeddings=embeddings_list, # The number representations
        metadatas=all_metadatas,   # Extra info (source file, etc.)
    )
    
    summary = {
        "status": "success",
        "documents_processed": len(doc_files),
        "total_chunks": len(all_chunks),
        "embedding_model": EMBEDDING_MODEL_NAME,
        "db_path": str(CHROMA_DB_PATH.resolve()),
    }
    
    print(f"\n✅ Done! Ingested {len(doc_files)} document(s) → {len(all_chunks)} chunks")
    print(f"   Database saved to: {CHROMA_DB_PATH.resolve()}")
    
    return summary


# This block runs only when you execute this file directly:
#   python -m src.rag.ingest
# It does NOT run when another file imports from this module.
if __name__ == "__main__":
    result = ingest_documents()
    print(f"\nResult: {result}")
