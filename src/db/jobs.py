"""
src/db/jobs.py
━━━━━━━━━━━━━
PostgreSQL replacement for src/jobs/database.py.
All queries are scoped to user_id (RLS enforced at DB level as safety net).
"""

import hashlib
import logging
from datetime import datetime

from src.db.connection import get_conn

logger = logging.getLogger(__name__)


def make_job_id(title: str, company: str) -> str:
    """Stable dedup key from title + company."""
    raw = f"{title.strip().lower()}|{company.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def upsert_job(scored_job, user_id: int) -> bool:
    """
    Insert or update a job for a specific user.
    Returns True if new, False if already existed.
    """
    job = scored_job.job
    job_id = make_job_id(job.title, job.company)
    now = datetime.now().isoformat(timespec="seconds")

    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            # Check existence
            cur.execute(
                "SELECT job_id FROM jobs WHERE job_id = %s AND user_id = %s",
                (job_id, user_id)
            )
            exists = cur.fetchone()

            if exists:
                cur.execute("""
                    UPDATE jobs SET
                        last_seen    = %s,
                        rag_score    = %s,
                        llm_score    = %s,
                        verdict      = %s,
                        seniority    = %s,
                        company_tier = %s,
                        fit_reason   = %s,
                        red_flags    = %s
                    WHERE job_id = %s AND user_id = %s
                """, (
                    now,
                    scored_job.score,
                    scored_job.llm_score,
                    scored_job.verdict,
                    scored_job.seniority,
                    scored_job.company_tier,
                    scored_job.fit_reason,
                    scored_job.red_flags,
                    job_id, user_id,
                ))
                return False

            cur.execute("""
                INSERT INTO jobs (
                    job_id, user_id, title, company, location, url, description, source,
                    rag_score, llm_score, verdict, seniority, company_tier,
                    career_path, fit_reason, red_flags,
                    status, first_seen, last_seen
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    'NEW', %s, %s
                )
            """, (
                job_id, user_id,
                job.title, job.company, job.location, job.url,
                (job.description or "")[:500],
                job.source,
                scored_job.score, scored_job.llm_score, scored_job.verdict,
                scored_job.seniority, scored_job.company_tier,
                getattr(scored_job, "career_path", ""),
                scored_job.fit_reason, scored_job.red_flags,
                now, now,
            ))
            return True


def get_unnotified_jobs(user_id: int) -> list[dict]:
    """Jobs not yet sent to Telegram for this user."""
    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT job_id, title, company, location, url,
                       rag_score, llm_score, verdict, seniority,
                       company_tier, career_path, fit_reason, red_flags,
                       status, first_seen
                FROM jobs
                WHERE notified_at IS NULL AND verdict != 'SKIP'
                  AND user_id = %s
                ORDER BY llm_score DESC
            """, (user_id,))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def mark_notified(job_ids: list[str], user_id: int):
    """Mark jobs as sent to Telegram."""
    if not job_ids:
        return
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE jobs SET notified_at = %s WHERE job_id = %s AND user_id = %s",
                [(now, jid, user_id) for jid in job_ids],
            )


def update_status(job_id: str, user_id: int, status: str, notes: str = "") -> bool:
    """Update job application status."""
    valid = {"NEW", "interested", "applied", "interviewing", "rejected", "skipped"}
    if status.lower() not in valid:
        return False

    now = datetime.now().isoformat(timespec="seconds")
    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            if status.lower() == "applied":
                cur.execute("""
                    UPDATE jobs SET status = %s, applied_at = %s, notes = %s
                    WHERE job_id = %s AND user_id = %s
                """, (status, now, notes, job_id, user_id))
            else:
                cur.execute("""
                    UPDATE jobs SET status = %s, notes = %s
                    WHERE job_id = %s AND user_id = %s
                """, (status, notes, job_id, user_id))
            return cur.rowcount > 0


def get_jobs_by_status(user_id: int, status: str) -> list[dict]:
    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM jobs WHERE status = %s AND user_id = %s
                ORDER BY llm_score DESC
            """, (status, user_id))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def search_jobs(user_id: int, query: str) -> list[dict]:
    pattern = f"%{query}%"
    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM jobs
                WHERE (title ILIKE %s OR company ILIKE %s) AND user_id = %s
                ORDER BY llm_score DESC
            """, (pattern, pattern, user_id))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_stats(user_id: int) -> dict:
    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM jobs WHERE user_id = %s", (user_id,))
            total = cur.fetchone()[0]

            cur.execute("""
                SELECT status, COUNT(*) FROM jobs WHERE user_id = %s GROUP BY status
            """, (user_id,))
            by_status = {r[0]: r[1] for r in cur.fetchall()}

            cur.execute("""
                SELECT AVG(rag_score), AVG(llm_score) FROM jobs WHERE user_id = %s
            """, (user_id,))
            avgs = cur.fetchone()

            cur.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE user_id = %s AND first_seen >= NOW() - INTERVAL '1 day'
            """, (user_id,))
            recent = cur.fetchone()[0]

    return {
        "total": total,
        "by_status": by_status,
        "avg_rag": round(avgs[0] or 0, 1),
        "avg_llm": round(avgs[1] or 0, 1),
        "new_last_24h": recent,
    }


def get_all_jobs(user_id: int, limit: int = 50) -> list[dict]:
    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM jobs WHERE user_id = %s
                ORDER BY first_seen DESC LIMIT %s
            """, (user_id, limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_job_by_id(job_id: str, user_id: int) -> dict | None:
    with get_conn(user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM jobs WHERE job_id = %s AND user_id = %s",
                (job_id, user_id)
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
