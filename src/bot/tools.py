"""
CareerBot — Agent Tools (Function Calling)

Usa supabase-py (HTTPS) como driver de banco — sem problemas de TCP/IPv6
em ambientes Serverless (Vercel Lambda).
"""
import json
import os
import hashlib
import httpx
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from src.rag.retriever import score_job
from src.db.client import get_client

LEARNED_PREFS_PATH = Path(__file__).parent.parent.parent / "data" / "learned_preferences.md"

# ---------- TOOL FUNCTIONS ----------

def get_recent_jobs(days: int = 7, limit: int = 10, user_id: int = None) -> str:
    """
    Fetch recent job matches from the database.
    Returns a JSON string with job details and scores.
    """
    if not user_id:
        return json.dumps({"error": "user_id is missing"})
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        result = (
            get_client()
            .table("jobs")
            .select(
                "job_id, title, company, location, rag_score, llm_score, "
                "verdict, seniority, company_tier, fit_reason, status, url, first_seen"
            )
            .eq("user_id", user_id)
            .gte("first_seen", cutoff)
            .order("llm_score", desc=True)
            .limit(limit)
            .execute()
        )
        jobs = result.data or []
        return json.dumps({"jobs": jobs, "count": len(jobs)}, ensure_ascii=False, default=str)
    except Exception:
        logging.exception("Erro técnico ao buscar vagas recentes")
        return json.dumps({"error": "Erro interno ao buscar as vagas. Verifique SUPABASE_SERVICE_KEY."})


def get_job_detail(job_id: str = "", company: str = "", title: str = "", user_id: int = None) -> str:
    if not user_id:
        return json.dumps({"error": "user_id is missing"})
    try:
        client = get_client()
        if job_id:
            result = client.table("jobs").select("*").eq("job_id", job_id).eq("user_id", user_id).limit(1).execute()
        elif company:
            result = client.table("jobs").select("*").eq("user_id", user_id).ilike("company", f"%{company}%").order("llm_score", desc=True).limit(1).execute()
        elif title:
            result = client.table("jobs").select("*").eq("user_id", user_id).ilike("title", f"%{title}%").order("llm_score", desc=True).limit(1).execute()
        else:
            return json.dumps({"error": "Forneça job_id, company ou title"})

        if not result.data:
            return json.dumps({"error": "Vaga não encontrada"})
        return json.dumps(result.data[0], ensure_ascii=False, default=str)
    except Exception:
        logging.exception("Erro técnico ao detalhar vaga")
        return json.dumps({"error": "Erro interno ao detalhar a vaga."})


def update_job_status(job_id: str, status: str, user_id: int = None) -> str:
    if not user_id:
        return json.dumps({"error": "user_id is missing"})
    valid = {"interested", "applied", "interviewing", "rejected", "skipped", "offer"}
    if status not in valid:
        return json.dumps({"error": f"Status inválido. Use: {', '.join(valid)}"})
    try:
        client = get_client()
        # Confirma que a vaga pertence ao user
        check = client.table("jobs").select("job_id").eq("job_id", job_id).eq("user_id", user_id).limit(1).execute()
        if not check.data:
            return json.dumps({"error": f"Vaga {job_id} não encontrada"})

        now = datetime.now().isoformat(timespec="seconds")
        update_payload: dict = {"status": status}
        if status == "applied":
            update_payload["applied_at"] = now

        client.table("jobs").update(update_payload).eq("job_id", job_id).eq("user_id", user_id).execute()
        return json.dumps({"success": True, "job_id": job_id, "new_status": status})
    except Exception:
        logging.exception("Erro ao atualizar status")
        return json.dumps({"error": "Erro interno ao atualizar o status."})


def get_application_stats(user_id: int = None) -> str:
    if not user_id:
        return json.dumps({"error": "user_id is missing"})
    try:
        client = get_client()
        # Busca todos os jobs do usuário para calcular stats em Python
        result = client.table("jobs").select("status, title, company, applied_at").eq("user_id", user_id).execute()
        rows = result.data or []

        total = len(rows)
        by_status: dict = {}
        for r in rows:
            s = r.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1

        # Últimas 5 candidaturas
        applied = sorted(
            [r for r in rows if r.get("status") == "applied" and r.get("applied_at")],
            key=lambda x: x["applied_at"], reverse=True
        )[:5]
        recently_applied = [{"title": r["title"], "company": r["company"], "applied_at": r["applied_at"]} for r in applied]

        return json.dumps({
            "total_analyzed": total,
            "by_status": by_status,
            "recently_applied": recently_applied,
        }, ensure_ascii=False, default=str)
    except Exception:
        logging.exception("Erro ao buscar stats")
        return json.dumps({"error": "Erro interno ao buscar estatísticas."})


def get_pending_followups(user_id: int = None) -> str:
    if not user_id:
        return json.dumps({"error": "user_id is missing"})
    try:
        cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
        result = (
            get_client()
            .table("jobs")
            .select("job_id, title, company, llm_score, first_seen")
            .eq("user_id", user_id)
            .eq("status", "interested")
            .lte("first_seen", cutoff)
            .order("llm_score", desc=True)
            .execute()
        )
        jobs = result.data or []
        return json.dumps({"pending": jobs, "count": len(jobs)}, ensure_ascii=False, default=str)
    except Exception:
        logging.exception("Erro pendencias")
        return json.dumps({"error": "Erro ao buscar follow-ups pendentes."})


def analyze_and_save_url(url: str, user_id: int = None) -> str:
    if not user_id:
        return json.dumps({"error": "user_id is missing"})
    try:
        parsed_url = urlparse(url)
        if parsed_url.scheme != "https":
            return json.dumps({"error": "Apenas URLs seguras (https://) são permitidas."})
        hostname = parsed_url.hostname or ""
        if hostname in ("169.254.169.254",) or any(hostname.startswith(p) for p in ("127.", "10.", "192.168.")):
            return json.dumps({"error": "Acesso a endereços internos não é permitido."})

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        with httpx.Client(timeout=10.0, follow_redirects=False) as http:
            resp = http.get(url, headers=headers)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.extract()
        text = soup.get_text(separator="\n")
        clean_text = "\n".join(chunk for chunk in (line.strip() for line in text.splitlines()) if chunk)
        desc_text = clean_text[:6000]

        title = soup.title.string.split("|")[0].strip() if soup.title else "Vaga via URL"
        company = soup.title.string.split("|")[-1].strip() if soup.title and "|" in soup.title.string else "Empresa Desconhecida"

        rag_result = score_job(desc_text)
        llm_result = classify_job(title=title, company=company, location="Remoto / Info via URL", description=desc_text, tier="paid", user_id=user_id)

        now = datetime.now().isoformat(timespec="seconds")
        job_id = "url_" + hashlib.md5(url.encode()).hexdigest()[:10]

        get_client().table("jobs").upsert({
            "job_id": job_id, "user_id": user_id, "title": title, "company": company,
            "location": "Remoto / Info via URL", "url": url, "description": desc_text[:500],
            "source": "Manual_URL", "rag_score": rag_result["score"],
            "llm_score": llm_result["llm_score"], "verdict": llm_result["verdict"],
            "seniority": llm_result["seniority"], "company_tier": llm_result["company_tier"],
            "career_path": "URL", "fit_reason": llm_result["fit_reason"],
            "red_flags": llm_result["red_flags"], "status": "interested",
            "first_seen": now, "last_seen": now,
        }, on_conflict="job_id,user_id").execute()

        return json.dumps({"success": True, "job_id": job_id, "title": title,
                           "rag_score": rag_result["score"], "llm_score": llm_result["llm_score"],
                           "fit_reason": llm_result["fit_reason"]}, ensure_ascii=False, default=str)
    except Exception:
        logging.exception("Erro ao analisar URL")
        return json.dumps({"error": "Erro ao processar e salvar vaga pela URL."})


def learn_from_job(job_id: str, user_id: int = None) -> str:
    if not user_id:
        return json.dumps({"error": "user_id is missing"})
    try:
        result = (
            get_client()
            .table("jobs")
            .select("description, title, company")
            .eq("job_id", job_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return json.dumps({"error": f"Vaga {job_id} não encontrada no banco."})

        row = result.data[0]
        desc, title, company = row.get("description", ""), row.get("title", ""), row.get("company", "")
        if not desc or len(desc.strip()) < 50:
            return json.dumps({"error": "Vaga sem descrição suficiente para aprender."})

        from google import genai
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            return json.dumps({"error": "GEMINI_API_KEY não configurada."})
        ai_client = genai.Client(api_key=api_key)
        prompt = (f"Leia esta vaga:\nTítulo: {title}\nEmpresa: {company}\n"
                  f"Descrição: {desc[:4000]}\n\nListe apenas 3 a 5 habilidades "
                  "que parecem ser o diferencial desta vaga. Formate como uma linha CSV.")

        response = ai_client.models.generate_content(model="gemini-2.0-flash-lite", contents=prompt)
        keywords = response.text.replace("\n", "").strip()

        return json.dumps({"success": True, "learned_keywords": keywords}, ensure_ascii=False)
    except Exception:
        logging.exception(f"Erro ao aprender com vaga {job_id}")
        return json.dumps({"error": "Erro ao tentar processar o aprendizado da vaga."})



def _clean_api_key(key: str) -> str:
    """Remove brackets, quotes, and whitespace from API key strings."""
    key = key.strip()
    if key.startswith("[") and key.endswith("]"):
        key = key[1:-1].strip()
    if key.startswith('"') and key.endswith('"'):
        key = key[1:-1]
    return key


def save_api_keys(free_key: str = "", paid_key: str | None = None, user_id: int = None) -> str:
    """
    BYOK legado — não mais usado. Informa ao usuário que o pipeline é centralizado.
    """
    return json.dumps({
        "success": True,
        "message": (
            "ℹ️ O sistema não precisa mais de chaves pessoais.\n"
            "O pipeline usa provedores LLM centralizados (NVIDIA NIM + Groq).\n"
            "Configure seu perfil de carreira com /set_profile para começar!"
        )
    })


def update_career_profile(summary_text: str, user_id: int = None) -> str:
    """
    Onboarding tool: save career summary and rebuild RAG vectors for the user.
    Called by the agent when the user provides their career description.
    """
    if not user_id:
        return json.dumps({"error": "user_id is missing"})
    if not summary_text or len(summary_text.strip()) < 100:
        return json.dumps({"error": "Resumo muito curto. Descreva sua experiência em pelo menos 100 caracteres."})
    try:
        import asyncio
        from src.rag.ingest import build_vector_db_for_user
        from src.db.users import set_career_profile

        # build_vector_db_for_user is async — run in event loop
        try:
            loop = asyncio.get_event_loop()
            vectors = loop.run_until_complete(build_vector_db_for_user(user_id, career_text=summary_text))
        except RuntimeError:
            # If already in async context, create a new loop
            vectors = asyncio.run(build_vector_db_for_user(user_id, career_text=summary_text))

        set_career_profile(user_id, career_summary=summary_text, career_vectors=vectors)
        return json.dumps({
            "success": True,
            "message": "✅ Perfil de carreira salvo e vetores gerados! O pipeline já pode rodar para você.",
        })
    except Exception as e:
        logging.exception(f"Error updating profile for user {user_id}")
        return json.dumps({"error": f"Erro ao atualizar perfil: {e}"})


def update_search_config(
    career_paths_json: str = "",
    locations: str = "",
    include_remote: bool = True,
    max_days_old: int = 7,
    user_id: int = None,
) -> str:
    """
    Salva a configuração de busca de vagas do usuário (quais cargos procurar, em qual cidade).
    Chamada pelo agente quando o usuário descreve suas preferências de busca.

    Args:
        career_paths_json: JSON string com lista de career paths.
            Ex: '[{"name": "Dados", "queries": ["Data Analyst", "Analista de Dados"], "weight": 1.0}]'
        locations: Localidades separadas por vírgula. Ex: 'São Paulo, Brazil'
        include_remote: True para incluir vagas remotas.
        max_days_old: Quantos dias de vagas buscar (7 = semana passada).
        user_id: Injetado automaticamente pelo agente.
    """
    if not user_id:
        return json.dumps({"error": "user_id is missing"})

    from src.db.users import set_search_config
    from src.jobs.config import CAREER_PATHS as DEFAULT_PATHS, LOCATIONS as DEFAULT_LOCS

    # Parse career_paths
    if career_paths_json:
        try:
            career_paths = json.loads(career_paths_json)
            if not isinstance(career_paths, list) or not career_paths:
                return json.dumps({"error": "career_paths_json deve ser uma lista JSON não-vazia."})
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"JSON inválido em career_paths_json: {e}"})
    else:
        career_paths = DEFAULT_PATHS

    # Parse locations
    locs = [l.strip() for l in locations.split(",") if l.strip()] if locations else DEFAULT_LOCS

    config = {
        "career_paths":   career_paths,
        "locations":      locs,
        "include_remote": include_remote,
        "max_days_old":   max_days_old,
    }

    ok = set_search_config(user_id, config)
    if ok:
        paths_summary = ", ".join(cp["name"] for cp in career_paths)
        return json.dumps({
            "success": True,
            "message": f"Configuração salva! Paths: {paths_summary} | Locais: {', '.join(locs)}",
        }, ensure_ascii=False)
    return json.dumps({"error": "Falha ao salvar no banco. Tente novamente."})


TOOL_DECLARATIONS = [
    {"name": "get_recent_jobs", "description": "Busca vagas recentes encontradas pelo pipeline. Use quando o usuário perguntar sobre vagas da semana, melhores vagas, ou qualquer listagem de oportunidades.", "parameters": {"type": "object", "properties": {"days": {"type": "integer", "description": "Dias atrás (padrão: 7)"}, "limit": {"type": "integer", "description": "Máximo (padrão: 10)"}}}},
    {"name": "get_job_detail", "description": "Retorna detalhes completos de uma vaga específica.", "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}, "company": {"type": "string"}, "title": {"type": "string"}}}},
    {"name": "update_job_status", "description": "Atualiza o status de uma vaga: interested, applied, interviewing, rejected, skipped, offer", "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}, "status": {"type": "string"}}, "required": ["job_id", "status"]}},
    {"name": "get_application_stats", "description": "Retorna estatísticas gerais.", "parameters": {"type": "object", "properties": {}}},
    {"name": "get_pending_followups", "description": "Lista vagas marcadas como interessante sem aplicação.", "parameters": {"type": "object", "properties": {}}},
    {"name": "learn_from_job", "description": "Extrai e salva competências de uma vaga.", "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
    {
        "name": "save_api_keys",
        "description": (
            "Salva as chaves de API Gemini do usuário de forma segura e criptografada no banco de dados. "
            "Use IMEDIATAMENTE quando o usuário fornecer uma chave (começa com 'AIza') em qualquer mensagem. "
            "A chave gratuita é obrigatória. A chave paga é opcional mas aumenta o número de vagas analisadas pelo pipeline."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "free_key": {"type": "string", "description": "Chave Gemini gratuita (começa com AIza). Obrigatória."},
                "paid_key": {"type": "string", "description": "Chave Gemini paga (opcional). Permite análise completa no pipeline."},
            },
            "required": ["free_key"],
        },
    },
    {
        "name": "update_search_config",
        "description": (
            "Salva a configuração de busca de vagas do usuário: quais cargos buscar, em qual cidade, "
            "se inclui remotas e quantos dias de vagas considerar. "
            "Use quando o usuário disser 'quero buscar vagas de X' ou 'mude minha busca para Y'. "
            "career_paths_json é uma lista JSON com name, queries[] e weight opcional. "
            "locations é uma string separada por vírgulas (ex: 'São Paulo, Brazil')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "career_paths_json": {
                    "type": "string",
                    "description": "JSON com lista de career paths. Ex: [{\"name\": \"Dados\", \"queries\": [\"Data Analyst\", \"Analista de Dados\"], \"weight\": 1.0}]",
                },
                "locations": {
                    "type": "string",
                    "description": "Cidades de busca separadas por vírgula. Ex: 'São Paulo, Brazil'",
                },
                "include_remote": {
                    "type": "boolean",
                    "description": "Incluir vagas remotas? (padrão: true)",
                },
                "max_days_old": {
                    "type": "integer",
                    "description": "Quantos dias de vagas buscar (padrão: 7)",
                },
            },
            "required": ["career_paths_json"],
        },
    },
    {
        "name": "update_career_profile",
        "description": (
            "Salva ou atualiza o resumo de carreira do usuário e regenera os vetores de busca (RAG). "
            "Use quando o usuário quiser configurar ou alterar seu perfil. "
            "Não use para atualizações parciais — o texto completo deve ser passado."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary_text": {
                    "type": "string",
                    "description": "Texto completo do resumo de carreira do usuário (mínimo 100 caracteres).",
                },
            },
            "required": ["summary_text"],
        },
    },
]

TOOL_EXECUTOR = {
    "get_recent_jobs":      get_recent_jobs,
    "get_job_detail":       get_job_detail,
    "update_job_status":    update_job_status,
    "get_application_stats": get_application_stats,
    "get_pending_followups": get_pending_followups,
    "learn_from_job":       learn_from_job,
    "save_api_keys":        save_api_keys,          # stub — mantido para compatibilidade
    "update_career_profile": update_career_profile,
    "update_search_config": update_search_config,
}
