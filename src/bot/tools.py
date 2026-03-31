"""
CareerBot — Agent Tools (Function Calling)

These are the functions the Gemini agent can call autonomously
when it needs data to answer the user's questions.
"""
import json
import os
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
import logging
from urllib.parse import urlparse

from src.rag.retriever import score_job
from src.jobs.classifier import classify_job
from src.bot.key_router import get_key
from src.db.connection import get_conn

LEARNED_PREFS_PATH = Path(__file__).parent.parent.parent / "data" / "learned_preferences.md"

# ---------- TOOL FUNCTIONS ----------

def get_recent_jobs(days: int = 7, limit: int = 10, user_id: int = None) -> str:
    """
    Fetch recent job matches from the database.
    Returns a JSON string with job details and scores.
    """
    if not user_id: return json.dumps({"error": "user_id is missing"})
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with get_conn(user_id) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT job_id as id, title, company, location, rag_score, llm_score,
                           verdict, seniority, company_tier, fit_reason, status, url, first_seen as created_at
                    FROM jobs
                    WHERE first_seen >= %s AND user_id = %s
                    ORDER BY llm_score DESC
                    LIMIT %s
                """, (cutoff, user_id, limit))
                jobs = [dict(r) for r in cur.fetchall()]
        return json.dumps({"jobs": jobs, "count": len(jobs)}, ensure_ascii=False, default=str)
    except Exception as e:
        logging.exception("Erro técnico ao buscar vagas recentes")
        return json.dumps({"error": "Ocorreu um erro interno ao buscar as vagas remotas. Verifique os logs."})


def get_job_detail(job_id: str = "", company: str = "", title: str = "", user_id: int = None) -> str:
    if not user_id: return json.dumps({"error": "user_id is missing"})
    try:
        with get_conn(user_id) as conn:
            with conn.cursor() as cur:
                if job_id:
                    cur.execute("SELECT * FROM jobs WHERE job_id = %s AND user_id = %s", (job_id, user_id))
                elif company:
                    cur.execute("SELECT * FROM jobs WHERE company ILIKE %s AND user_id = %s ORDER BY llm_score DESC LIMIT 1", (f"%{company}%", user_id))
                elif title:
                    cur.execute("SELECT * FROM jobs WHERE title ILIKE %s AND user_id = %s ORDER BY llm_score DESC LIMIT 1", (f"%{title}%", user_id))
                else:
                    return json.dumps({"error": "Forneça job_id, company ou title"})
                
                row = cur.fetchone()
                if not row:
                    return json.dumps({"error": "Vaga não encontrada"})
                
                return json.dumps(dict(row), ensure_ascii=False, default=str)
    except Exception as e:
        logging.exception("Erro técnico ao detalhar vaga")
        return json.dumps({"error": "Erro interno ao detalhar a vaga."})


def update_job_status(job_id: str, status: str, user_id: int = None) -> str:
    if not user_id: return json.dumps({"error": "user_id is missing"})
    valid = {"interested", "applied", "interviewing", "rejected", "skipped", "offer"}
    if status not in valid:
        return json.dumps({"error": f"Status inválido. Use: {', '.join(valid)}"})
    try:
        now = datetime.now().isoformat(timespec="seconds")
        with get_conn(user_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT job_id FROM jobs WHERE job_id = %s AND user_id = %s", (job_id, user_id))
                if not cur.fetchone():
                    return json.dumps({"error": f"Vaga {job_id} não encontrada"})
                
                if status == "applied":
                    cur.execute("UPDATE jobs SET status = %s, applied_at = %s WHERE job_id = %s AND user_id = %s", (status, now, job_id, user_id))
                else:
                    cur.execute("UPDATE jobs SET status = %s WHERE job_id = %s AND user_id = %s", (status, job_id, user_id))
        return json.dumps({"success": True, "job_id": job_id, "new_status": status})
    except Exception as e:
        logging.exception("Erro ao atualizar status")
        return json.dumps({"error": "Erro interno ao atualizar o status."})


def get_application_stats(user_id: int = None) -> str:
    if not user_id: return json.dumps({"error": "user_id is missing"})
    try:
        with get_conn(user_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as total FROM jobs WHERE user_id = %s", (user_id,))
                total = cur.fetchone()["total"]
                
                cur.execute("SELECT status, COUNT(*) as cnt FROM jobs WHERE user_id = %s GROUP BY status", (user_id,))
                by_status = {r["status"]: r["cnt"] for r in cur.fetchall()}
                
                cur.execute("""
                    SELECT title, company, applied_at 
                    FROM jobs WHERE status = 'applied' AND user_id = %s
                    ORDER BY applied_at DESC LIMIT 5
                """, (user_id,))
                recent = [{"title": r[0], "company": r[1], "applied_at": str(r[2])} for r in cur.fetchall()]
                
        return json.dumps({"total_analyzed": total, "by_status": by_status, "recently_applied": recent}, ensure_ascii=False, default=str)
    except Exception as e:
        logging.exception("Erro ao buscar stats")
        return json.dumps({"error": "Erro interno ao buscar estatísticas."})


def get_pending_followups(user_id: int = None) -> str:
    if not user_id: return json.dumps({"error": "user_id is missing"})
    try:
        cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        with get_conn(user_id) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT job_id as id, title, company, llm_score as combined_score, first_seen as created_at
                    FROM jobs
                    WHERE status = 'interested' AND first_seen <= %s AND user_id = %s
                    ORDER BY llm_score DESC
                """, (cutoff, user_id))
                jobs = [dict(r) for r in cur.fetchall()]
        return json.dumps({"pending": jobs, "count": len(jobs)}, ensure_ascii=False, default=str)
    except Exception as e:
        logging.exception("Erro pendencias")
        return json.dumps({"error": "Erro ao buscar follow-ups pendentes."})


def analyze_and_save_url(url: str, user_id: int = None) -> str:
    if not user_id: return json.dumps({"error": "user_id is missing"})
    try:
        parsed_url = urlparse(url)
        if parsed_url.scheme != 'https':
            return json.dumps({"error": "Apenas URLs seguras (https://) são permitidas."})
            
        hostname = parsed_url.hostname or ""
        if hostname == "169.254.169.254" or hostname.startswith("127.") or hostname.startswith("10.") or hostname.startswith("192.168."):
            return json.dumps({"error": "Acesso a endereços internos não é permitido."})

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            
        soup = BeautifulSoup(resp.text, "html.parser")
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
        text = soup.get_text(separator="\n")
        clean_text = "\n".join(chunk for chunk in (line.strip() for line in text.splitlines()) if chunk)
        desc_text = clean_text[:6000]
        
        title = soup.title.string.split("|")[0].strip() if soup.title else "Vaga via URL"
        company = soup.title.string.split("|")[-1].strip() if soup.title and "|" in soup.title.string else "Empresa Desconhecida"

        rag_result = score_job(desc_text)
        llm_result = classify_job(title=title, company=company, location="Remoto / Info via URL", description=desc_text, tier="paid", user_id=user_id)
        
        now = datetime.now().isoformat(timespec="seconds")
        import hashlib
        job_id = "url_" + hashlib.md5(url.encode()).hexdigest()[:10]
        
        with get_conn(user_id) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jobs (
                        job_id, user_id, title, company, location, url, description, source,
                        rag_score, llm_score, verdict, seniority, company_tier, career_path,
                        fit_reason, red_flags, status, first_seen, last_seen
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (job_id, user_id) DO NOTHING
                """, (
                    job_id, user_id, title, company, "Remoto / Info via URL", url, desc_text, "Manual_URL",
                    rag_result["score"], llm_result["llm_score"], llm_result["verdict"], llm_result["seniority"], llm_result["company_tier"], "URL",
                    llm_result["fit_reason"], llm_result["red_flags"], "interested", now, now
                ))

        return json.dumps({"success": True, "job_id": job_id, "title": title, "rag_score": rag_result["score"], "llm_score": llm_result["llm_score"], "fit_reason": llm_result["fit_reason"]}, ensure_ascii=False, default=str)
    except Exception as e:
        logging.exception("Erro ao analisar URL")
        return json.dumps({"error": "Erro ao processar e salvar vaga pela URL."})


def learn_from_job(job_id: str, user_id: int = None) -> str:
    if not user_id: return json.dumps({"error": "user_id is missing"})
    try:
        with get_conn(user_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT description, title, company FROM jobs WHERE job_id = %s AND user_id = %s", (job_id, user_id))
                row = cur.fetchone()
        
        if not row:
            return json.dumps({"error": f"Vaga {job_id} não encontrada no banco."})
            
        desc, title, company = row
        if not desc or len(desc.strip()) < 50:
            return json.dumps({"error": "Vaga sem descrição suficiente para aprender."})
            
        from google import genai
        api_key = get_key("paid", user_id)
        client = genai.Client(api_key=api_key)
        prompt = f"Leia esta vaga:\nTítulo: {title}\nEmpresa: {company}\nDescrição: {desc[:4000]}\n\nListe apenas 3 a 5 habilidades que parecem ser o diferencial desta vaga. Formate como uma linha CSV."
        
        response = client.models.generate_content(model="gemini-3.1-flash-lite-preview", contents=prompt)
        keywords = response.text.replace("\n", "").strip()
        
        LEARNED_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LEARNED_PREFS_PATH, "a", encoding="utf-8") as f:
            f.write(f"- {title} ({company}): {keywords}\n")
            
        return json.dumps({"success": True, "learned_keywords": keywords}, ensure_ascii=False)
    except Exception as e:
        logging.exception(f"Erro ao aprender com vaga {job_id}")
        return json.dumps({"error": "Erro ao tentar processar o aprendizado da vaga."})


TOOL_DECLARATIONS = [
    {"name": "get_recent_jobs", "description": "Busca vagas recentes encontradas pelo pipeline. Use quando o usuário perguntar sobre vagas da semana, melhores vagas, ou qualquer listagem de oportunidades.", "parameters": {"type": "object", "properties": {"days": {"type": "integer", "description": "Dias atrás (padrão: 7)"}, "limit": {"type": "integer", "description": "Máximo (padrão: 10)"}}}},
    {"name": "get_job_detail", "description": "Retorna detalhes completos de uma vaga específica.", "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}, "company": {"type": "string"}, "title": {"type": "string"}}}},
    {"name": "update_job_status", "description": "Atualiza o status de uma vaga: interested, applied, interviewing, rejected, skipped, offer", "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}, "status": {"type": "string"}}, "required": ["job_id", "status"]}},
    {"name": "get_application_stats", "description": "Retorna estatísticas gerais.", "parameters": {"type": "object", "properties": {}}},
    {"name": "get_pending_followups", "description": "Lista vagas marcadas como interessante sem aplicação.", "parameters": {"type": "object", "properties": {}}},
    {"name": "analyze_and_save_url", "description": "Scraping de URL e salva no banco.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "learn_from_job", "description": "Extrai e salva competências de uma vaga.", "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
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
