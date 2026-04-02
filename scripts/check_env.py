"""
scripts/check_env.py
━━━━━━━━━━━━━━━━━━━
Diagnóstico estruturado do ambiente de execução do GitHub Actions.
Reporta presença de secrets, conectividade TCP e resolução DNS.
NUNCA imprime os valores reais das secrets.
"""

import os
import socket
import sys
import urllib.parse
from datetime import datetime, timezone


def ts():
    """Timestamp UTC para logs estruturados."""
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
    # SECTION 1: Environment Variables
    # ─────────────────────────────────────────────────────────
    section("1. Environment Variables (Secrets)")

    required = {
        "DATABASE_URL":          "Primary DB connection (Transaction Pooler preferred)",
        "SUPABASE_URL":          "REST API URL for Supabase SDK",
        "SUPABASE_SERVICE_KEY":  "Admin key for server-side Supabase access",
        "ENCRYPTION_MASTER_KEY": "Fernet master key for BYOK user key decryption",
        "TELEGRAM_BOT_TOKEN":    "Telegram Bot API token",
    }

    # Optional system-level fallback keys (used ONLY during onboarding for new users)
    optional = {
        "GEMINI_FREE_API_KEY":  "System fallback — onboarding only (new users w/ no BYOK key)",
        "GEMINI_PAID_API_KEY":  "System fallback — onboarding only (optional, paid tier)",
        "POSTGRES_URL":         "Fallback DB alias (set by Vercel-Supabase integration)",
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
    info("Optional / System Fallback Keys (BYOK multi-tenant — not required for pipeline):")
    for var, description in optional.items():
        val = os.environ.get(var, "")
        if val:
            ok(f"  {var:<26} defined  (len={len(val)})  # {description}")
        else:
            warn(f"  {var:<26} not set  # {description}")

    if any_missing:
        warn("One or more REQUIRED variables are missing. The pipeline WILL fail.")
    else:
        ok("All required environment variables are present.")

    # ─────────────────────────────────────────────────────────
    # SECTION 2: Database URL Analysis
    # ─────────────────────────────────────────────────────────
    section("2. Database URL Analysis")

    db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not db_url:
        fail("No DB URL found (neither DATABASE_URL nor POSTGRES_URL). Cannot continue.")
    else:
        try:
            parsed = urllib.parse.urlparse(db_url)
            host = parsed.hostname
            port = parsed.port or 5432
            scheme = parsed.scheme

            info(f"Scheme   : {scheme}")
            info(f"Host     : {host}")
            info(f"Port     : {port}")
            info(f"DB Name  : {parsed.path.lstrip('/')}")

            # Warn about common pool mismatches
            if port == 5432:
                warn("Using direct connection port (5432). Recommended: Transaction Pooler port 6543 for serverless.")
            elif port == 6543:
                ok("Using Transaction Pooler port (6543). Good for serverless.")

            # Check URL scheme compatibility (psycopg2 needs postgresql://)
            if scheme == "postgres":
                warn("Scheme is 'postgres://' — psycopg2 requires 'postgresql://'. May cause connection errors.")
            elif scheme == "postgresql":
                ok("Scheme is 'postgresql://'. Compatible with psycopg2.")

        except Exception as e:
            fail(f"Could not parse DATABASE_URL: {e}")

    # ─────────────────────────────────────────────────────────
    # SECTION 3: TCP Connectivity
    # ─────────────────────────────────────────────────────────
    section("3. TCP Connectivity to Database Host")

    if db_url:
        try:
            parsed = urllib.parse.urlparse(db_url)
            host = parsed.hostname
            port = parsed.port or 5432
            info(f"Attempting TCP connection to {host}:{port} (timeout=10s)...")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((host, port))
            s.close()
            ok(f"TCP handshake to {host}:{port} successful. Network path is open.")
        except socket.timeout:
            fail(f"TCP connection to {host}:{port} timed out. Firewall or IP block?")
        except socket.gaierror as e:
            fail(f"DNS resolution failed for '{host}': {e}")
        except Exception as e:
            fail(f"Connection error: {type(e).__name__}: {e}")
    else:
        warn("Skipped (no DB URL).")

    # ─────────────────────────────────────────────────────────
    # SECTION 4: DNS Resolution for External APIs
    # ─────────────────────────────────────────────────────────
    section("4. DNS Resolution for External APIs")

    apis = [
        "api.telegram.org",
        "generativelanguage.googleapis.com",
    ]
    if db_url:
        try:
            host = urllib.parse.urlparse(db_url).hostname
            if host:
                apis.insert(0, host)
        except Exception:
            pass

    for host in apis:
        try:
            ip = socket.gethostbyname(host)
            ok(f"Resolved {host:<45} → {ip}")
        except socket.gaierror as e:
            fail(f"Could not resolve {host}: {e}")

    # ─────────────────────────────────────────────────────────
    # SECTION 5: Python path sanity check
    # ─────────────────────────────────────────────────────────
    section("5. Python Path & Module Sanity")

    modules_to_check = [
        ("psycopg2", "PostgreSQL driver"),
        ("supabase", "Supabase SDK"),
        ("telegram", "python-telegram-bot"),
        ("google.genai", "Gemini AI SDK"),
        ("cryptography", "Fernet encryption"),
        ("jobspy", "JobSpy scraper"),
    ]
    for mod, label in modules_to_check:
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
