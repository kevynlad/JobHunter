"""
=============================================================
🤖 CLASSIFIER.PY — Gemini LLM Job Classifier
=============================================================

Uses Gemini 2.5 Flash Lite to analyze job postings.
Rate limit: 20 requests/minute (free tier).

=============================================================
"""

import os
import json
import re
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.bot.key_router import get_key_pool


# Gemini API Configuration
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Career summary — loaded from external file (gitignored) to protect personal data
_SUMMARY_PATH = Path(__file__).parent.parent.parent / "career_summary.txt"
_LEARNED_PREFS_PATH = Path(__file__).parent.parent.parent / "data" / "learned_preferences.md"

def _load_career_summary() -> str:
    """Load career summary: file → CAREER_SUMMARY env var → MASTER_PROFILE env var."""
    if _SUMMARY_PATH.exists():
        return _SUMMARY_PATH.read_text(encoding="utf-8")
    # Priority 1: dedicated CAREER_SUMMARY env var (set in Railway)
    career_summary = os.getenv("CAREER_SUMMARY", "").strip()
    if career_summary:
        print("[i] Using CAREER_SUMMARY env var for classifier.")
        return career_summary
    # Priority 2: fall back to full MASTER_PROFILE
    master = os.getenv("MASTER_PROFILE", "").strip()
    if master:
        print("[i] Using MASTER_PROFILE env var for classifier (no CAREER_SUMMARY set).")
        return master
    print(f"[!] career_summary.txt not found and no env vars set.")
    return "No career summary configured."


CAREER_SUMMARY = _load_career_summary()


_current_key_idx = 0

def _call_gemini(prompt: str, tier: str = "free", max_retries: int = 3) -> dict | None:
    """
    Call Gemini API with automatic retry on rate limits.
    Handles truncated JSON from thinking models via partial recovery.
    Supports a pool of API Keys for load balancing.
    """
    global _current_key_idx
    
    # Use the specified tier key pool
    from src.bot.key_router import get_key_pool
    keys = get_key_pool(tier)
    if not keys:
        return None
    
    for attempt in range(max_retries):
        try:
            current_key = keys[_current_key_idx]
            response = httpx.post(
                f"{GEMINI_API_URL}?key={current_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": 512,          # JSON output is small (~200 tokens)
                        "response_mime_type": "application/json",  # Structured output guarantee
                        "thinkingConfig": {"thinkingBudget": 0}    # Disable thinking for speed
                    },
                },
                timeout=45,
            )
            response.raise_for_status()
            data = response.json()
            
            # Gemini 2.5 thinking models: last part = actual output
            parts = data["candidates"][0]["content"]["parts"]
            text = parts[-1].get("text", "")
            text = text.strip()
            
            # Clean markdown code blocks
            if text.startswith("```"):
                text = re.sub(r"```(?:json)?\s*", "", text)
                text = text.rstrip("`").strip()
            
            # Try full JSON parse
            try:
                json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                return json.loads(text)
            except json.JSONDecodeError:
                # Partial JSON recovery for truncated responses
                return _extract_partial_json(text)
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                body = e.response.text
                print(f"  ⚠️ Rate limit na Chave {_current_key_idx + 1}/{len(keys)}")
                
                # If we have more than one key, just rotate to the next one instantly
                if len(keys) > 1:
                    _current_key_idx = (_current_key_idx + 1) % len(keys)
                    print(f"  🔄 Trocando para a Chave {_current_key_idx + 1}...")
                    time.sleep(3) # tiny break before new key
                    continue
                
                # If only 1 key, fallback to waiting
                retry_match = re.search(r"retry in (\d+\.?\d*)", body, re.IGNORECASE)
                wait_time = float(retry_match.group(1)) + 2 if retry_match else 65
                wait_time = min(wait_time, 120)
                
                if attempt < max_retries - 1:
                    print(f"  ⏳ Aguardando {wait_time:.0f}s (tentativa {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"  ❌ Limite persistente após {max_retries} tentativas")
                    return None
            else:
                print(f"  ❌ Gemini API error: {e.response.status_code}")
                return None
        except Exception as e:
            print(f"  ❌ LLM error: {e}")
            return None
    
    return None


def _extract_partial_json(text: str) -> dict | None:
    """
    Extract fields from truncated JSON responses.
    Gemini 2.5 thinking models sometimes truncate fit_reason mid-sentence.
    This recovers the critical fields (score, seniority, tier, verdict).
    """
    result = {}
    
    score_m = re.search(r'"llm_score"\s*:\s*(\d+)', text)
    if score_m:
        result["llm_score"] = int(score_m.group(1))
    
    sen_m = re.search(r'"seniority"\s*:\s*"([^"]*)"', text)
    if sen_m:
        result["seniority"] = sen_m.group(1)
    
    tier_m = re.search(r'"company_tier"\s*:\s*"([^"]*)"', text)
    if tier_m:
        result["company_tier"] = tier_m.group(1)
    
    verdict_m = re.search(r'"verdict"\s*:\s*"([^"]*)"', text)
    if verdict_m:
        result["verdict"] = verdict_m.group(1)
    
    reason_m = re.search(r'"fit_reason"\s*:\s*"([^"]*)', text)
    if reason_m:
        reason = reason_m.group(1).rstrip("\\")
        result["fit_reason"] = reason + "..." if len(reason) > 50 else reason
    
    flags_m = re.search(r'"red_flags"\s*:\s*"([^"]*)', text)
    if flags_m:
        result["red_flags"] = flags_m.group(1).rstrip("\\")
    
    return result if "llm_score" in result else None


def classify_job(title: str, company: str, location: str, description: str, tier: str = "free") -> dict:
    """
    Predict match score and extract metadata via Gemini LLM.
    Returns a dict with: llm_score, seniority, company_tier, fit_reason, red_flags, verdict.
    """
    desc_truncated = (description[:4000] + "...") if description and len(description) > 4000 else (description or "No description provided.")
    
    learned_prefs = _LEARNED_PREFS_PATH.read_text(encoding="utf-8").strip() if _LEARNED_PREFS_PATH.exists() else ""
    prefs_section = f"\n[COMPETÊNCIAS APRENDIDAS - O usuário prioriza estas características (dê MUITO MAIS PESO no llm_score se bater com isso)]:\n{learned_prefs}\n" if learned_prefs else ""
    
    prompt = f"""Você é um estrategista de carreira pragmático e focado em resultados reais.
Sua missão é avaliar vagas para o candidato abaixo, que busca a efetivação no mercado como Analista, deixando para trás o título de estagiário. 

{CAREER_SUMMARY}
{prefs_section}
JOB:
Title: {title}
Company: {company}
Location: {location}
Description: {desc_truncated}

DIRETRIZES DE PENSAMENTO:
1. Alinhamento de Cargo: É uma vaga de Analista (Dados, Produto, Negócios, Ops), Product Ops, Product Manager (PM) ou Product Owner (PO)? Se sim, é um ótimo alvo. Valorize IGUALMENTE essas áreas.
2. Filtro de Gestão: A vaga é estritamente para gestão de pessoas (Engineering Manager, Head, Diretor)? Se sim, marque como SKIP. ATENÇÃO: 'Product Manager' e 'Product Owner' NÃO SÃO cargos de gestão de pessoas, são Individual Contributors (ICs). Portanto, para PM e PO, NÃO DÊ SKIP e avalie normalmente!
3. Fit Técnico: A vaga pede habilidades do candidato? Considere TANTO habilidades técnicas (SQL, Python, Dashboards) QUANTO habilidades de produto/ops (priorização, stakeholders, jornada do usuário, processos).
4. Veredito: Seja encorajador mas realista. O candidato se destaca tanto como bridge entre Produto e Engenharia (Product Ops) quanto como Analista de Dados com impacto em negócio.

Respond ONLY with JSON (no markdown):
{{
    "llm_score": <0-100>,
    "seniority": "<Jr|Pleno|Senior|Lead|Unknown>",
    "company_tier": "<Large|Mid|Startup|Unknown>",
    "fit_reason": "<Parágrafo ácido e honesto analisando a qualidade da vaga. Destaque o impacto (GMV, Automação)>",
    "red_flags": "<Preocupações de ser operacional demais ou 'None'>",
    "verdict": "<APPLY|MAYBE|SKIP>"
}}

SCORING:
- 90-100: Perfect (right seniority/tier combination, great company, exact fit)
- 70-89: Good (mostly fits, worth applying)
- 50-69: Weak (some fit but concerns)
- 0-49: Poor (wrong level/area, red flags)

Be strict. Jr at unknown consulting = <40. Jr/Pleno at Large Fintech = >75.
"""

    result = _call_gemini(prompt, tier=tier)
    
    if result is None:
        return _default_result("LLM unavailable")
    
    return {
        "llm_score": int(result.get("llm_score", 50)),
        "seniority": result.get("seniority", "Unknown"),
        "company_tier": result.get("company_tier", "Unknown"),
        "fit_reason": result.get("fit_reason", ""),
        "red_flags": result.get("red_flags", "None"),
        "verdict": result.get("verdict", "MAYBE"),
    }


def classify_jobs_batch(scored_jobs: list, max_classify: int = 30, tier: str = "free") -> list:
    """
    Classify the top RAG-scored jobs with Gemini.
    
    tier="free" -> zero cost, but sets a ~4.5s delay per job (safely under 15 RPM).
    tier="paid" -> near-instant (0.5s delay), costs money.
    """
    from src.bot.key_router import get_key_pool
    keys = get_key_pool(tier)
    
    to_classify = scored_jobs[:max_classify]
    skip_count = len(scored_jobs) - len(to_classify)
    
    print(f"\n  🤖 Classifying top {len(to_classify)} jobs with Gemini ({GEMINI_MODEL}) on {tier.upper()} tier...")
    if skip_count > 0:
        print(f"  (skipping {skip_count} lower-scored candidates)")
    
    classified = []
    for i, sj in enumerate(to_classify):
        # Adaptive delay to stay within rate limits
        if i > 0:
            delay = 4.5 if tier == "free" else 0.5
            time.sleep(delay)
        
        result = classify_job(
            title=sj.job.title,
            company=sj.job.company,
            location=sj.job.location,
            description=sj.job.description,
            tier=tier
        )
        
        # Merge results into the ScoredJob object
        sj.llm_score = result["llm_score"]
        sj.seniority = result["seniority"]
        sj.company_tier = result["company_tier"]
        sj.fit_reason = result["fit_reason"]
        sj.red_flags = result["red_flags"]
        sj.verdict = result["verdict"]
        
        classified.append(sj)
        
        # Progress log
        if (i + 1) % 5 == 0 or (i + 1) == len(to_classify):
            print(f"    [{i+1}/{len(to_classify)}] {sj.job.company}: {sj.llm_score}% ({sj.verdict})")
            
    return classified


def _default_result(reason: str) -> dict:
    return {
        "llm_score": 50,
        "seniority": "Unknown",
        "company_tier": "Unknown",
        "fit_reason": reason,
        "red_flags": "Could not classify",
        "verdict": "MAYBE",
    }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    result = classify_job(
        title="Senior Product Manager",
        company="PicPay",
        description="Buscamos PM sênior para liderar produto. Requisitos: 5+ anos, Python, SQL.",
        location="São Paulo, SP",
    )
    
    print("Classification result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
