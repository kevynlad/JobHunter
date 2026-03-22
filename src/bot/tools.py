"""
CareerBot — Agent Tools (Function Calling)

These are the functions the Gemini agent can call autonomously
when it needs data to answer the user's questions.
"""
import json
import os
import sqlite3
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path

from src.rag.retriever import score_job
from src.jobs.classifier import classify_job
from src.bot.key_router import get_key


DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
LEARNED_PREFS_PATH = Path(__file__).parent.parent.parent / "data" / "learned_preferences.md"


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
            SELECT job_id as id, title, company, location, rag_score, llm_score,
                   verdict, seniority, company_tier,
                   fit_reason, status, url, first_seen as created_at
            FROM jobs
            WHERE first_seen >= ?
            ORDER BY llm_score DESC
            LIMIT ?
        """, (cutoff, limit)).fetchall()
        conn.close()

        cols = ["id", "title", "company", "location", "rag_score", "llm_score",
                "verdict", "seniority", "company_tier",
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
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        elif company:
            row = conn.execute(
                "SELECT * FROM jobs WHERE company LIKE ? ORDER BY llm_score DESC LIMIT 1",
                (f"%{company}%",)
            ).fetchone()
        elif title:
            row = conn.execute(
                "SELECT * FROM jobs WHERE title LIKE ? ORDER BY llm_score DESC LIMIT 1",
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
        exists = conn.execute("SELECT job_id FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not exists:
            conn.close()
            return json.dumps({"error": f"Vaga {job_id} não encontrada"})

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        if status == "applied":
            conn.execute(
                "UPDATE jobs SET status = ?, applied_at = ? WHERE job_id = ?",
                (status, now, job_id)
            )
        else:
            conn.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
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
            SELECT job_id as id, title, company, llm_score as combined_score, first_seen as created_at
            FROM jobs
            WHERE status = 'interested'
            AND first_seen <= ?
            ORDER BY llm_score DESC
        """, (cutoff,)).fetchall()
        conn.close()
        jobs = [
            {"id": r[0], "title": r[1], "company": r[2], "score": r[3], "found_at": r[4]}
            for r in rows
        ]
        return json.dumps({"pending": jobs, "count": len(jobs)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def analyze_and_save_url(url: str) -> str:
    """
    Fetch a job URL, read text, score it, classify it, and save it to the DB if good.
    """
    try:
        # 1. Fetch text
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            
        soup = BeautifulSoup(resp.text, "html.parser")
        # Kill scripts and styles
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
        text = soup.get_text(separator="\n")
        lines = (line.strip() for line in text.splitlines())
        clean_text = "\n".join(chunk for chunk in lines if chunk)
        
        # Limit text size to front-load important description
        desc_text = clean_text[:6000]
        
        # Very basic naive title/company extraction (since it's raw HTML)
        title = soup.title.string.split("|")[0].strip() if soup.title else "Vaga via URL"
        company = soup.title.string.split("|")[-1].strip() if soup.title and "|" in soup.title.string else "Empresa Desconhecida"

        # 2. Score with RAG
        rag_result = score_job(desc_text)
        rag_score = rag_result["score"]
        
        # 3. Classify with LLM
        llm_result = classify_job(
            title=title,
            company=company,
            location="Vaga via URL",
            description=desc_text,
            tier="paid"
        )
        llm_score = llm_result["llm_score"]
        
        # 4. Save to Database
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        import hashlib
        job_id = "url_" + hashlib.md5(url.encode()).hexdigest()[:10]
        
        conn = _get_db()
        # insert or ignore
        conn.execute("""
            INSERT OR IGNORE INTO jobs (
                job_id, title, company, location, url, description, source,
                rag_score, llm_score, verdict, seniority, company_tier, career_path,
                fit_reason, red_flags, status, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id, title, company, "Remoto / Info via URL", url, desc_text, "Manual_URL",
            rag_score, llm_score, llm_result["verdict"], llm_result["seniority"], llm_result["company_tier"], "URL",
            llm_result["fit_reason"], llm_result["red_flags"], "interested", now, now
        ))
        conn.commit()
        conn.close()
        
        return json.dumps({
            "success": True,
            "job_id": job_id,
            "title": title,
            "rag_score": rag_score,
            "llm_score": llm_score,
            "fit_reason": llm_result["fit_reason"]
        }, ensure_ascii=False)
        
    except httpx.HTTPError as e:
        return json.dumps({"error": f"Erro ao acessar a URL: {str(e)}"})
    except Exception as e:
        return json.dumps({"error": f"Erro ao analisar vaga: {str(e)}"})


def learn_from_job(job_id: str) -> str:
    """
    Extracts vital competencies from an interesting job and saves them to long-term memory.
    """
    try:
        conn = _get_db()
        row = conn.execute("SELECT description, title, company FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        conn.close()
        
        if not row:
            return json.dumps({"error": f"Vaga {job_id} não encontrada no banco."})
            
        desc, title, company = row
        if not desc or len(desc.strip()) < 50:
            return json.dumps({"error": "Vaga sem descrição suficiente para aprender."})
            
        from google import genai
        api_key = get_key("paid")  # Use paid key: this is a quality extraction task
        client = genai.Client(api_key=api_key)
        prompt = f"Leia esta vaga:\nTítulo: {title}\nEmpresa: {company}\nDescrição: {desc[:4000]}\n\nListe apenas 3 a 5 habilidades (hard ou soft) ou palavras-chave estratégicas que parecem ser o diferencial desta vaga, as quais o usuário demonstrou interesse. Formate apenas como uma linha separada por vírgulas."
        
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
        )
        keywords = response.text.replace("\n", "").strip()
        
        LEARNED_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LEARNED_PREFS_PATH, "a", encoding="utf-8") as f:
            f.write(f"- {title} ({company}): {keywords}\n")
            
        return json.dumps({"success": True, "learned_keywords": keywords}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Erro ao aprender com a vaga: {str(e)}"})


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
    {
        "name": "analyze_and_save_url",
        "description": "Faça o scraping de uma URL fornecida pelo usuário, calcule a aderência de carreira e salve no banco de dados.",
        "parameters": {
            "type": "object", 
            "properties": {
                "url": {"type": "string", "description": "URL da vaga (LinkedIn, Gupy, etc.)"}
            },
            "required": ["url"]
        },
    },
    {
        "name": "learn_from_job",
        "description": "Extrai e salva as competências de uma vaga preferida pelo usuário na memória de longo prazo. Use quando o usuário elogiar muito uma vaga ou marcá-la como 'interested' ou 'applied'.",
        "parameters": {
            "type": "object", 
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga para aprendizado"}
            },
            "required": ["job_id"]
        },
    },
]

TOOL_EXECUTOR = {
    "get_recent_jobs": get_recent_jobs,
    "get_job_detail": get_job_detail,
    "update_job_status": update_job_status,
    "get_application_stats": get_application_stats,
    "get_pending_followups": get_pending_followups,
    "analyze_and_save_url": analyze_and_save_url,
    "learn_from_job": learn_from_job,
}
