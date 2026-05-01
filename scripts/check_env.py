"""
scripts/check_env.py
━━━━━━━━━━━━━━━━━━━
Diagnóstico do ambiente de execução do GitHub Actions.

Arquitetura atual (V2 - Centralizada):
  - LLM: NVIDIA NIM + Groq (chaves no Supabase Vault)
  - Embeddings/RAG: Gemini gemini-embedding-001 (chave no Supabase Vault)
  - DB: Supabase SDK (HTTPS) + psycopg2 (TCP direto)
  - Sem BYOK, sem ENCRYPTION_MASTER_KEY

NUNCA imprime os valores reais dos secrets.
"""

import os
import socket
import sys
import urllib.parse
from datetime import datetime, timezone


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"[{ts()}] SECTION: {title}")
    print(f"{'─' * 60}")


def ok(msg: str):
    print(f"[{ts()}] ✅  {msg}")


def fail(msg: str):
    print(f"[{ts()}] ❌  {msg}")


def warn(msg: str):
    print(f"[{ts()}] ⚠️   {msg}")


def info(msg: str):
    print(f"[{ts()}]     {msg}")


def check_env():
    print("=" * 60)
    print(f"[{ts()}] 🔍  JOBHUNTER PIPELINE DIAGNOSTIC REPORT")
    print(f"       Python {sys.version}")
    print(f"       CWD: {os.getcwd()}")
    print("=" * 60)

    # ─────────────────────────────────────────────────────────
    # SECTION 1: Required Secrets (GitHub Actions)
    # ─────────────────────────────────────────────────────────
    section("1. Environment Variables (GitHub Secrets)")

    required = {
        "DATABASE_URL":         "PostgreSQL direct connection (Transaction Pooler port 6543)",
        "SUPABASE_URL":         "REST API URL for Supabase SDK",
        "SUPABASE_SERVICE_KEY": "Admin key — bypasses RLS (server-side only)",
        "TELEGRAM_BOT_TOKEN":   "Telegram Bot API token",
    }

    any_missing = False
    for var, description in required.items():
        val = os.environ.get(var, "")
        if val:
            ok(f"{var:<28} defined  (len={len(val)})  # {description}")
        else:
            fail(f"{var:<28} MISSING  # {description}")
            any_missing = True

    info("")
    info("LLM/Embedding keys are loaded from Supabase Vault at runtime.")
    info("  → NVIDIA_API_KEY  (key_router.py → NVIDIA NIM)")
    info("  → GROQ_API_KEY    (key_router.py → Groq / Llama 3)")
    info("  → GEMINI_API_KEY  (retriever.py  → gemini-embedding-001)")

    if any_missing:
        warn("One or more REQUIRED variables are missing. The pipeline WILL fail.")
    else:
        ok("All required environment variables are present.")

    # ─────────────────────────────────────────────────────────
    # SECTION 2: Database URL Analysis
    # ─────────────────────────────────────────────────────────
    section("2. Database URL Analysis")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        fail("DATABASE_URL not set. Cannot continue.")
    else:
        try:
            parsed = urllib.parse.urlparse(db_url)
            host = parsed.hostname
            port = parsed.port or 5432

            info(f"Scheme   : {parsed.scheme}")
            info(f"Host     : {host}")
            info(f"Port     : {port}")
            info(f"DB Name  : {parsed.path.lstrip('/')}")

            if port == 5432:
                warn("Direct connection (5432). Prefer Transaction Pooler port 6543 for GitHub Actions.")
            elif port == 6543:
                ok("Transaction Pooler port (6543). ✓")

            if parsed.scheme == "postgres":
                warn("Scheme 'postgres://' — psycopg2 requires 'postgresql://'. May fail.")
            elif parsed.scheme == "postgresql":
                ok("Scheme 'postgresql://'. ✓")

        except Exception as e:
            fail(f"Could not parse DATABASE_URL: {e}")

    # ─────────────────────────────────────────────────────────
    # SECTION 3: TCP Connectivity
    # ─────────────────────────────────────────────────────────
    section("3. TCP Connectivity to Database")

    if db_url:
        try:
            parsed = urllib.parse.urlparse(db_url)
            host = parsed.hostname
            port = parsed.port or 5432
            info(f"Attempting TCP to {host}:{port} (timeout=10s)...")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((host, port))
            s.close()
            ok(f"TCP handshake to {host}:{port} succeeded. ✓")
        except socket.timeout:
            fail(f"TCP to {host}:{port} timed out. Firewall or IP block?")
        except socket.gaierror as e:
            fail(f"DNS resolution failed for '{host}': {e}")
        except Exception as e:
            fail(f"Connection error: {type(e).__name__}: {e}")
    else:
        warn("Skipped (no DATABASE_URL).")

    # ─────────────────────────────────────────────────────────
    # SECTION 4: DNS Resolution for External APIs
    # ─────────────────────────────────────────────────────────
    section("4. DNS Resolution for External APIs")

    apis = [
        ("api.telegram.org",                   "Telegram Bot API"),
        ("generativelanguage.googleapis.com",   "Gemini Embedding API"),
        ("integrate.api.nvidia.com",            "NVIDIA NIM API"),
        ("api.groq.com",                        "Groq API"),
    ]

    for host, label in apis:
        try:
            ip = socket.gethostbyname(host)
            ok(f"{host:<45} → {ip}  # {label}")
        except socket.gaierror as e:
            fail(f"Could not resolve {host}  # {label}: {e}")

    # ─────────────────────────────────────────────────────────
    # SECTION 5: Python Module Sanity
    # ─────────────────────────────────────────────────────────
    section("5. Python Module Sanity")

    modules = [
        ("psycopg2",      "PostgreSQL driver"),
        ("supabase",      "Supabase SDK"),
        ("telegram",      "python-telegram-bot"),
        ("google.genai",  "Gemini AI SDK (embeddings)"),
        ("openai",        "OpenAI-compatible client (NVIDIA NIM / Groq)"),
        ("jobspy",        "JobSpy scraper"),
        ("pandas",        "DataFrame processing"),
        ("cryptography",  "Fernet (optional — legacy compat)"),
    ]

    for mod, label in modules:
        try:
            __import__(mod)
            ok(f"{mod:<25} importable  # {label}")
        except ImportError as e:
            fail(f"{mod:<25} IMPORT ERROR: {e}  # {label}")

    print("\n" + "=" * 60)
    print(f"[{ts()}] 📊  END OF DIAGNOSTIC")
    print("=" * 60)


if __name__ == "__main__":
    check_env()
