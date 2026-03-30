"""
scripts/migrate_sqlite_to_pg.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One-shot migration: SQLite jobs.db → Supabase PostgreSQL.

Usage (after setting DATABASE_URL in .env):
    python scripts/migrate_sqlite_to_pg.py

Your Telegram ID (1643296714) becomes user_id = 1 in the new system.
"""

import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────
SQLITE_PATH    = Path(__file__).parent.parent / "data" / "jobs.db"
DATABASE_URL   = os.environ["DATABASE_URL"]   # Supabase connection string
YOUR_USER_ID   = int(os.environ.get("TELEGRAM_CHAT_ID", "1643296714"))
YOUR_FIRST_NAME = "Kevyn"

CAREER_VECTORS_PATH = Path(__file__).parent.parent / "data" / "career_vectors.json"
CAREER_SUMMARY_PATH = Path(__file__).parent.parent / "career_summary.txt"


def _encrypt_key(raw: str) -> str:
    """Encrypt a Gemini API key using the MASTER_KEY from env."""
    from cryptography.fernet import Fernet
    master = os.environ["ENCRYPTION_MASTER_KEY"].encode()
    return Fernet(master).encrypt(raw.encode()).decode()


def migrate():
    print("=" * 60)
    print("  JobHunter SQLite -> Supabase Migration")
    print("=" * 60)

    # -- Connect -----------------------------------------------
    pg  = psycopg2.connect(DATABASE_URL)
    pg.autocommit = False
    cur = pg.cursor()

    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    try:
        # ── 1. Insert yourself as user_id ─────────────────────
        print(f"\n[1] Creating user {YOUR_USER_ID} ({YOUR_FIRST_NAME})...")

        career_summary = ""
        if CAREER_SUMMARY_PATH.exists():
            career_summary = CAREER_SUMMARY_PATH.read_text(encoding="utf-8")
        else:
            career_summary = os.getenv("CAREER_SUMMARY", "")

        career_vectors_json = None
        if CAREER_VECTORS_PATH.exists():
            career_vectors_json = json.dumps(
                json.loads(CAREER_VECTORS_PATH.read_text(encoding="utf-8"))
            )

        free_key  = os.getenv("GEMINI_FREE_API_KEY", "")
        paid_key  = os.getenv("GEMINI_PAID_API_KEY", "")

        enc_free = _encrypt_key(free_key)  if free_key  else None
        enc_paid = _encrypt_key(paid_key)  if paid_key  else None

        cur.execute("""
            INSERT INTO users (user_id, first_name, gemini_free_key, gemini_paid_key,
                               career_summary, career_vectors, onboarding_step)
            VALUES (%s, %s, %s, %s, %s, %s, 'ready')
            ON CONFLICT (user_id) DO UPDATE SET
                gemini_free_key  = EXCLUDED.gemini_free_key,
                gemini_paid_key  = EXCLUDED.gemini_paid_key,
                career_summary   = EXCLUDED.career_summary,
                career_vectors   = EXCLUDED.career_vectors,
                onboarding_step  = 'ready'
        """, (YOUR_USER_ID, YOUR_FIRST_NAME, enc_free, enc_paid,
              career_summary, career_vectors_json))

        print("    ✅ User created/updated")

        # ── 2. Migrate jobs ───────────────────────────────────
        print("\n[2] Migrating jobs from SQLite...")

        rows = sqlite_conn.execute("SELECT * FROM jobs").fetchall()
        cols = [d[0] for d in sqlite_conn.execute("SELECT * FROM jobs WHERE 1=0").description]
        print(f"    Found {len(rows)} jobs to migrate")

        def _ts(val):
            """Convert SQLite text timestamp to ISO format or None."""
            if not val:
                return None
            try:
                # Try common formats
                for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(val, fmt).isoformat()
                    except ValueError:
                        continue
            except Exception:
                pass
            return None

        job_rows = []
        for row in rows:
            d = dict(zip(cols, row))
            job_rows.append((
                d.get("job_id", ""),
                YOUR_USER_ID,
                d.get("title", ""),
                d.get("company", ""),
                d.get("location", ""),
                d.get("url", ""),
                (d.get("description") or "")[:2000],
                d.get("source", ""),
                d.get("rag_score", 0),
                d.get("llm_score", 0),
                d.get("verdict", ""),
                d.get("seniority", ""),
                d.get("company_tier", ""),
                d.get("career_path", ""),
                d.get("fit_reason", ""),
                d.get("red_flags", ""),
                d.get("status", "NEW"),
                _ts(d.get("first_seen")) or datetime.now().isoformat(),
                _ts(d.get("last_seen"))  or datetime.now().isoformat(),
                _ts(d.get("notified_at")),
                _ts(d.get("applied_at")),
                d.get("notes", ""),
            ))

        execute_values(cur, """
            INSERT INTO jobs (
                job_id, user_id, title, company, location, url, description, source,
                rag_score, llm_score, verdict, seniority, company_tier, career_path,
                fit_reason, red_flags, status, first_seen, last_seen,
                notified_at, applied_at, notes
            ) VALUES %s
            ON CONFLICT (job_id, user_id) DO NOTHING
        """, job_rows)

        pg.commit()
        print(f"    ✅ {len(job_rows)} jobs migrated")

    except Exception as e:
        pg.rollback()
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        cur.close()
        pg.close()
        sqlite_conn.close()

    print("\n" + "=" * 60)
    print("  ✅ Migration complete!")
    print(f"  Your user_id in Supabase: {YOUR_USER_ID}")
    print("=" * 60)


if __name__ == "__main__":
    migrate()
