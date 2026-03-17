"""
=============================================================
💾 DATABASE.PY — SQLite Job Tracker
=============================================================

Persistent storage for job postings. Handles:
- Deduplication: same job won't be notified twice
- Status tracking: NEW → APPLIED / SKIPPED / IGNORED
- History: when a job was first seen, last seen, notified

=============================================================
"""

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

# Database location
DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def _get_conn() -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Access columns by name
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
    return conn


def init_db():
    """Create the jobs table if it doesn't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id       TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            company      TEXT NOT NULL,
            location     TEXT DEFAULT '',
            url          TEXT DEFAULT '',
            description  TEXT DEFAULT '',
            source       TEXT DEFAULT '',
            
            rag_score    REAL DEFAULT 0,
            llm_score    INTEGER DEFAULT 0,
            verdict      TEXT DEFAULT '',
            seniority    TEXT DEFAULT '',
            company_tier TEXT DEFAULT '',
            career_path  TEXT DEFAULT '',
            fit_reason   TEXT DEFAULT '',
            red_flags    TEXT DEFAULT '',
            
            status       TEXT DEFAULT 'NEW',
            first_seen   TEXT NOT NULL,
            last_seen    TEXT NOT NULL,
            notified_at  TEXT DEFAULT '',
            applied_at   TEXT DEFAULT '',
            notes        TEXT DEFAULT '',

            -- Generated documents (stored as binary PDF or text)
            cover_letter_text TEXT DEFAULT '',
            cover_letter_pdf  BLOB DEFAULT NULL,
            cv_pdf            BLOB DEFAULT NULL
        );
        
        CREATE INDEX IF NOT EXISTS idx_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_llm_score ON jobs(llm_score);
        CREATE INDEX IF NOT EXISTS idx_first_seen ON jobs(first_seen);
    """)
    # Migration: add columns to existing databases that don't have them yet
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    migrations = {
        "cover_letter_text": "ALTER TABLE jobs ADD COLUMN cover_letter_text TEXT DEFAULT ''",
        "cover_letter_pdf":  "ALTER TABLE jobs ADD COLUMN cover_letter_pdf BLOB DEFAULT NULL",
        "cv_pdf":            "ALTER TABLE jobs ADD COLUMN cv_pdf BLOB DEFAULT NULL",
    }
    for col, sql in migrations.items():
        if col not in existing_cols:
            conn.execute(sql)
    conn.commit()
    conn.close()


def make_job_id(title: str, company: str) -> str:
    """Generate a stable dedup key from title + company."""
    raw = f"{title.strip().lower()}|{company.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def upsert_job(scored_job) -> bool:
    """
    Insert a new job or update an existing one.
    
    Returns True if the job is NEW (first time seen).
    Returns False if the job already existed (just updated last_seen).
    """
    job = scored_job.job
    job_id = make_job_id(job.title, job.company)
    now = datetime.now().isoformat(timespec="seconds")
    
    conn = _get_conn()
    
    # Check if job already exists
    existing = conn.execute(
        "SELECT job_id, status FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    
    if existing:
        # Job already in DB — update last_seen and scores (but keep status)
        conn.execute("""
            UPDATE jobs SET
                last_seen = ?,
                rag_score = ?,
                llm_score = ?,
                verdict = ?,
                seniority = ?,
                company_tier = ?,
                fit_reason = ?,
                red_flags = ?
            WHERE job_id = ?
        """, (
            now,
            scored_job.score,
            scored_job.llm_score,
            scored_job.verdict,
            scored_job.seniority,
            scored_job.company_tier,
            scored_job.fit_reason,
            scored_job.red_flags,
            job_id,
        ))
        conn.commit()
        conn.close()
        return False  # Not new
    else:
        # Brand new job
        conn.execute("""
            INSERT INTO jobs (
                job_id, title, company, location, url, description, source,
                rag_score, llm_score, verdict, seniority, company_tier,
                career_path, fit_reason, red_flags,
                status, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?, ?)
        """, (
            job_id, job.title, job.company, job.location, job.url,
            job.description[:500],  # Store truncated desc to save space
            job.source,
            scored_job.score, scored_job.llm_score, scored_job.verdict,
            scored_job.seniority, scored_job.company_tier,
            getattr(scored_job, 'career_path', ''),
            scored_job.fit_reason, scored_job.red_flags,
            now, now,
        ))
        conn.commit()
        conn.close()
        return True  # New job


def get_unnotified_jobs() -> list[dict]:
    """Get all jobs that haven't been sent to Telegram yet."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE notified_at = '' AND verdict != 'SKIP' ORDER BY llm_score DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_notified(job_ids: list[str]):
    """Mark jobs as sent to Telegram."""
    now = datetime.now().isoformat(timespec="seconds")
    conn = _get_conn()
    conn.executemany(
        "UPDATE jobs SET notified_at = ? WHERE job_id = ?",
        [(now, jid) for jid in job_ids],
    )
    conn.commit()
    conn.close()


def update_status(job_id: str, status: str, notes: str = "") -> bool:
    """
    Update job status. Valid statuses: NEW, APPLIED, SKIPPED, IGNORED.
    Returns True if the job was found and updated.
    """
    valid = {"NEW", "APPLIED", "SKIPPED", "IGNORED"}
    if status.upper() not in valid:
        return False
    
    conn = _get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    
    updates = {"status": status.upper()}
    if status.upper() == "APPLIED":
        updates["applied_at"] = now
    if notes:
        updates["notes"] = notes
    
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [job_id]
    
    result = conn.execute(f"UPDATE jobs SET {set_clause} WHERE job_id = ?", values)
    conn.commit()
    updated = result.rowcount > 0
    conn.close()
    return updated


def get_jobs_by_status(status: str) -> list[dict]:
    """Get all jobs with a given status."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = ? ORDER BY llm_score DESC",
        (status.upper(),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_jobs(query: str) -> list[dict]:
    """Search jobs by title or company (case-insensitive)."""
    conn = _get_conn()
    pattern = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM jobs WHERE title LIKE ? OR company LIKE ? ORDER BY llm_score DESC",
        (pattern, pattern),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    """Get summary statistics."""
    conn = _get_conn()
    
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    by_status = {}
    for row in conn.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"):
        by_status[row["status"]] = row["cnt"]
    
    avg_rag = conn.execute("SELECT AVG(rag_score) FROM jobs").fetchone()[0] or 0
    avg_llm = conn.execute("SELECT AVG(llm_score) FROM jobs").fetchone()[0] or 0
    
    recent = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE first_seen >= date('now', '-1 day')"
    ).fetchone()[0]
    
    conn.close()
    return {
        "total": total,
        "by_status": by_status,
        "avg_rag": round(avg_rag, 1),
        "avg_llm": round(avg_llm, 1),
        "new_last_24h": recent,
    }


def get_all_jobs(limit: int = 50) -> list[dict]:
    """Get all jobs ordered by most recent first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY first_seen DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Initialize DB on import
init_db()
