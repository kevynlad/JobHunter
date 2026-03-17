"""
CareerBot — Agent Tools (Function Calling)

These are the functions the Gemini agent can call autonomously
when it needs data to answer the user's questions.
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"


def _get_db():
    """Get a read connection to the jobs database."""
    db_path = os.getenv("JOBS_DB_PATH", str(DB_PATH))
    return sqlite3.connect(db_path)


# ---------- TOOL FUNCTIONS ----------

def get_recent_jobs(days: int = 7, limit: int = 10) -> str:
    """
    Fetch recent job matches from the database.
    Returns a JSON string with job details and scores.
    """
    try:
        conn = _get_db()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute("""
            SELECT id, title, company, location, rag_score, llm_score,
                   combined_score, verdict, seniority, company_tier,
                   fit_reason, status, url, created_at
            FROM jobs
            WHERE created_at >= ?
            ORDER BY combined_score DESC
            LIMIT ?
        """, (cutoff, limit)).fetchall()
        conn.close()

        cols = ["id", "title", "company", "location", "rag_score", "llm_score",
                "combined_score", "verdict", "seniority", "company_tier",
                "fit_reason", "status", "url", "created_at"]
        jobs = [dict(zip(cols, row)) for row in rows]
        return json.dumps({"jobs": jobs, "count": len(jobs)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_job_detail(job_id: str = "", company: str = "", title: str = "") -> str:
    """
    Get full details of a specific job by ID, company name, or title keyword.
    """
    try:
        conn = _get_db()
        if job_id:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        elif company:
            row = conn.execute(
                "SELECT * FROM jobs WHERE company LIKE ? ORDER BY combined_score DESC LIMIT 1",
                (f"%{company}%",)
            ).fetchone()
        elif title:
            row = conn.execute(
                "SELECT * FROM jobs WHERE title LIKE ? ORDER BY combined_score DESC LIMIT 1",
                (f"%{title}%",)
            ).fetchone()
        else:
            return json.dumps({"error": "Forneça job_id, company ou title"})

        conn.close()
        if not row:
            return json.dumps({"error": "Vaga não encontrada"})

        cols = [d[0] for d in conn.description] if hasattr(conn, 'description') else []
        # Fallback: get column names
        conn2 = _get_db()
        cursor = conn2.execute("SELECT * FROM jobs WHERE 1=0")
        cols = [d[0] for d in cursor.description]
        conn2.close()

        return json.dumps(dict(zip(cols, row)), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def update_job_status(job_id: str, status: str) -> str:
    """
    Update the status of a job.
    Valid statuses: 'interested', 'applied', 'interviewing', 'rejected', 'skipped'
    """
    valid = {"interested", "applied", "interviewing", "rejected", "skipped", "offer"}
    if status not in valid:
        return json.dumps({"error": f"Status inválido. Use: {', '.join(valid)}"})
    try:
        conn = _get_db()
        # Check the job exists
        exists = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not exists:
            conn.close()
            return json.dumps({"error": f"Vaga {job_id} não encontrada"})

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        if status == "applied":
            conn.execute(
                "UPDATE jobs SET status = ?, applied_at = ? WHERE id = ?",
                (status, now, job_id)
            )
        else:
            conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        conn.commit()
        conn.close()
        return json.dumps({"success": True, "job_id": job_id, "new_status": status})
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_application_stats() -> str:
    """
    Get a summary of all job application statuses.
    """
    try:
        conn = _get_db()
        # Total jobs analyzed
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        by_status = conn.execute(
            "SELECT status, COUNT(*) FROM jobs GROUP BY status"
        ).fetchall()
        recent_applied = conn.execute("""
            SELECT title, company, applied_at
            FROM jobs WHERE status = 'applied'
            ORDER BY applied_at DESC LIMIT 5
        """).fetchall()
        conn.close()

        return json.dumps({
            "total_analyzed": total,
            "by_status": dict(by_status),
            "recently_applied": [
                {"title": r[0], "company": r[1], "applied_at": r[2]}
                for r in recent_applied
            ]
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_pending_followups() -> str:
    """
    Get jobs that need follow-up (marked as interested but not applied).
    """
    try:
        conn = _get_db()
        cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        rows = conn.execute("""
            SELECT id, title, company, combined_score, created_at
            FROM jobs
            WHERE status = 'interested'
            AND created_at <= ?
            ORDER BY combined_score DESC
        """, (cutoff,)).fetchall()
        conn.close()
        jobs = [
            {"id": r[0], "title": r[1], "company": r[2], "score": r[3], "found_at": r[4]}
            for r in rows
        ]
        return json.dumps({"pending": jobs, "count": len(jobs)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------- GEMINI FUNCTION DECLARATIONS ----------
# These tell Gemini what tools are available and how to call them.

TOOL_DECLARATIONS = [
    {
        "name": "get_recent_jobs",
        "description": "Busca vagas recentes encontradas pelo pipeline. Use quando o usuário perguntar sobre vagas da semana, melhores vagas, ou qualquer listagem de oportunidades.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Quantos dias atrás buscar (padrão: 7)"},
                "limit": {"type": "integer", "description": "Número máximo de vagas (padrão: 10)"},
            },
        },
    },
    {
        "name": "get_job_detail",
        "description": "Retorna detalhes completos de uma vaga específica. Use quando o usuário perguntar sobre uma empresa ou cargo específico.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID único da vaga"},
                "company": {"type": "string", "description": "Nome da empresa (busca parcial)"},
                "title": {"type": "string", "description": "Título ou palavra-chave do cargo"},
            },
        },
    },
    {
        "name": "update_job_status",
        "description": "Atualiza o status de uma vaga quando o usuário informa que aplicou, está entrevistando, ou desistiu.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga"},
                "status": {"type": "string", "description": "Novo status: interested, applied, interviewing, rejected, skipped, offer"},
            },
            "required": ["job_id", "status"],
        },
    },
    {
        "name": "get_application_stats",
        "description": "Retorna estatísticas gerais da busca: total de vagas analisadas, distribuição por status, aplicações recentes.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_pending_followups",
        "description": "Lista vagas marcadas como interessante há mais de 3 dias mas ainda sem aplicação.",
        "parameters": {"type": "object", "properties": {}},
    },
]

TOOL_EXECUTOR = {
    "get_recent_jobs": get_recent_jobs,
    "get_job_detail": get_job_detail,
    "update_job_status": update_job_status,
    "get_application_stats": get_application_stats,
    "get_pending_followups": get_pending_followups,
}
