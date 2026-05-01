"""
=============================================================
🤖 CLASSIFIER.PY — LLM Job Classifier (NVIDIA NIM + Groq)
=============================================================

Classifica vagas usando o provedor LLM configurado no key_router.
Padrão: NVIDIA NIM (Nemotron) — 40 RPM gratuitos.
Fallback automático: Groq (Llama 3) se NVIDIA indisponível.

=============================================================
"""

import json
import time
import asyncio
from dotenv import load_dotenv

from src.jobs.models import ScoredJob
from src.bot.key_router import get_llm_client

load_dotenv()

async def _classify_job_async(
    job_title: str,
    company: str,
    location: str,
    description: str,
    career_summary: str,
    sem: asyncio.Semaphore,
) -> dict:
    """
    Asynchronously calls the configured LLM to classify a single job.
    Uses a semaphore to prevent exceeding rate limits.
    """
    try:
        client, model = get_llm_client("classify")
    except EnvironmentError as e:
        return _default_result(str(e))

    desc_truncated = (description[:3500] + "...") if description and len(description) > 3500 else (description or "No description provided.")

    system_instruction = f"""Você é um estrategista de carreira rigoroso e pragmático.
Sua missão é avaliar vagas de emprego para o candidato abaixo, retornando APENAS JSON válido.

PERFIL DO CANDIDATO:
{career_summary}

CRITÉRIOS DE PONTUAÇÃO (llm_score):
- 90-100: Encaixe perfeito (senioridade correta, empresa excelente, match exato de habilidades)
- 70-89: Bom encaixe, vale aplicar
- 50-69: Encaixe fraco, faltam habilidades ou senioridade questionável
- 0-49: Ruim (área completamente errada, red flags graves)

O JSON DEVE CONTER EXATAMENTE AS CHAVES:
"llm_score" (inteiro 0-100), "seniority" (string: Jr, Pleno, Senior, Lead, Unknown), "company_tier" (string: Large, Mid, Startup, Unknown), "fit_reason" (string curta justificando), "red_flags" (string ou "None"), "verdict" (string: APPLY, MAYBE, SKIP).
"""

    prompt = f"""JOB:
Title: {job_title}
Company: {company}
Location: {location}
Description: {desc_truncated}

Avalie a vaga acima em relação ao PERFIL DO CANDIDATO.
"""

    async with sem:
        for attempt in range(3):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=500,
                    response_format={"type": "json_object"}
                )
                
                content = response.choices[0].message.content
                parsed = json.loads(content)
                
                # Normalize keys just in case
                return {
                    "llm_score": int(parsed.get("llm_score", 50)),
                    "seniority": str(parsed.get("seniority", "Unknown")),
                    "company_tier": str(parsed.get("company_tier", "Unknown")),
                    "fit_reason": str(parsed.get("fit_reason", "")),
                    "red_flags": str(parsed.get("red_flags", "None")),
                    "verdict": str(parsed.get("verdict", "MAYBE")),
                }
            except Exception as e:
                if attempt == 2:
                    return _default_result(f"Error parsing LLM response: {str(e)}")
                await asyncio.sleep(2 * (attempt + 1))
        
        return _default_result("Failed after 3 retries")

async def _classify_batch_async(scored_jobs: list, career_summary: str, max_classify: int = 60) -> list:
    """Orchestrates concurrent classification for a batch of jobs."""
    to_classify = scored_jobs[:max_classify]
    
    # Use a semaphore of 20 to comfortably stay under 40 RPM
    sem = asyncio.Semaphore(20)
    
    tasks = []
    for sj in to_classify:
        tasks.append(
            _classify_job_async(
                job_title=sj.job.title,
                company=sj.job.company,
                location=sj.job.location,
                description=sj.job.description,
                career_summary=career_summary,
                sem=sem
            )
        )
    
    try:
        _, _model_name = get_llm_client("classify")
    except Exception:
        _model_name = "LLM"
    print(f"\n  🤖 Classifying top {len(to_classify)} jobs in parallel ({_model_name})...")
    start_time = time.time()
    
    results = await asyncio.gather(*tasks)
    
    # Merge results
    classified = []
    for sj, res in zip(to_classify, results):
        sj.llm_score = res["llm_score"]
        sj.seniority = res["seniority"]
        sj.company_tier = res["company_tier"]
        sj.fit_reason = res["fit_reason"]
        sj.red_flags = res["red_flags"]
        sj.verdict = res["verdict"]
        classified.append(sj)
        
    duration = time.time() - start_time
    print(f"  ✅ Batch classification completed in {duration:.2f}s!")
    
    return classified

def classify_jobs_batch(
    scored_jobs: list,
    max_classify: int = 60,
    tier: str = "paid", # Ignored in NVIDIA NIM logic
    user_id: int | None = None,
    career_summary: str | None = None,
) -> list:
    """
    Synchronous wrapper for the batch classification.
    career_summary MUST be provided for personalized analysis.
    """
    if not career_summary:
        print(f"  [!] Warning: No career_summary provided for user_id={user_id}. Classification will use fallback.")
        career_summary = "Profissional de dados e negócios em busca de vagas de nível Analista ou superior."
    
    return asyncio.run(_classify_batch_async(scored_jobs, career_summary, max_classify))

def _default_result(reason: str) -> dict:
    return {
        "llm_score": 50,
        "seniority": "Unknown",
        "company_tier": "Unknown",
        "fit_reason": reason,
        "red_flags": "Could not classify",
        "verdict": "MAYBE",
    }
