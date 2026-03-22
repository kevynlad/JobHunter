"""
=============================================================
🚀 PIPELINE.PY — Main JobHunter Pipeline
=============================================================

Flow:
  1. Search jobs (JSearch + Arbeitnow)
  2. Filter: SP metro area only
  3. Score with RAG (fast, vector similarity)
  4. Classify with Gemini LLM (deep analysis)
  5. Rank by combined score (RAG + LLM)
  6. Notify via Telegram (if ≥5 good jobs)
  7. Save CSV log

Run manually:   python -m src.pipeline
Run scheduled:  python -m src.notify.scheduler

=============================================================
"""

import sys
import os
import logging
from datetime import datetime

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from src.jobs.matcher import search_and_match, print_results
from src.jobs.classifier import classify_jobs_batch
from src.jobs.database import upsert_job, get_unnotified_jobs, mark_notified, make_job_id
from src.notify.telegram import send_telegram_message, send_job_cards_with_buttons


# Load environment variables
load_dotenv()


# ----- CONFIGURATION -----
SCORE_THRESHOLD = 45.0          # Minimum RAG score (Tightened for cost control)
LLM_SCORE_THRESHOLD = 60       # Minimum LLM score (Gemini)
MIN_JOBS_TO_NOTIFY = 5          # Need at least this many good jobs
MAX_JOBS_IN_NOTIFICATION = 15   # Show at most this many in Telegram


def run_pipeline() -> dict:
    """
    🚀 Run the full JobHunter pipeline.
    """
    try:
        logger.info("=" * 60)
        logger.info(f"  🚀 JobHunter Pipeline")
        logger.info(f"  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)
        
        all_scored = []
        rag_candidates = []
        classified = []
        good_matches = []
        notified = False

        # --- Step 1: Search + RAG Score ---
        logger.info("\n📌 Step 1: Searching and RAG scoring jobs...")
        try:
            all_scored = search_and_match(min_score=0)
        except Exception as e:
            logger.error(f"❌ search_and_match failed: {e}", exc_info=True)
            all_scored = []
        
        if not all_scored:
            logger.warning("\n❌ No jobs found or search failed.")
        else:
            # --- Step 2: Pre-filter by RAG score (≥SCORE_THRESHOLD%) ---
            rag_candidates = [sj for sj in all_scored if sj.score >= SCORE_THRESHOLD]
            logger.info(f"📊 RAG pre-filter: {len(all_scored)} → {len(rag_candidates)} candidates (≥{SCORE_THRESHOLD}%)")
            
            if rag_candidates:
                # --- Step 3: Classify with Gemini LLM (FREE TIER for background) ---
                logger.info("\n📌 Step 2: Deep analysis with Gemini AI (FREE Tier)...")
                classified = classify_jobs_batch(rag_candidates, max_classify=30, tier="free")
                
                # --- Step 4: Combined ranking + Filtering ---
                for sj in classified:
                    sj.combined_score = (sj.score * 0.4) + (sj.llm_score * 0.6)
                
                good_matches = [
                    sj for sj in classified
                    if sj.score >= SCORE_THRESHOLD and sj.llm_score >= LLM_SCORE_THRESHOLD
                    and sj.verdict != "SKIP"
                ]
                good_matches.sort(key=lambda sj: sj.combined_score, reverse=True)
            else:
                logger.info("No candidates passed RAG threshold.")
        
        # --- Step 5: Save to SQLite ---
        logger.info("\n💾 Saving results to database...")
        new_count = 0
        to_save = good_matches if good_matches else classified
        for sj in to_save:
            is_new = upsert_job(sj)
            if is_new:
                new_count += 1
        logger.info(f"  Saved {len(to_save)} jobs ({new_count} new)")
        
        # --- Step 6: Notify via Telegram (only NEW matches) ---
        unnotified = get_unnotified_jobs()
        if unnotified:
            logger.info(f"\n📱 Sending Telegram notification ({len(unnotified)} new matches)...")
            jobs_to_send = unnotified[:MAX_JOBS_IN_NOTIFICATION]
            success = send_job_cards_with_buttons(jobs_to_send, total_analyzed=len(all_scored))
            notified = success
            if success:
                mark_notified([j['job_id'] for j in unnotified])
                logger.info("✅ Telegram sent successfully")
            else:
                logger.error("❌ Telegram failed")
        
        # --- Step 7: Summary Report (Always Send) ---
        summary_lines = [
            f"🤖 <b>Pipeline Finalizado ({len(all_scored)} coletadas)</b>",
            f"🧠 Avançaram pro LLM (RAG ≥ {SCORE_THRESHOLD}%): <b>{len(rag_candidates)}</b>",
            f"✅ Aprovadas (LLM ≥ {LLM_SCORE_THRESHOLD}%): <b>{len(good_matches)}</b>\n",
        ]
        
        if rag_candidates:
            rejected = [sj for sj in classified if sj.verdict == "SKIP" or sj.llm_score < LLM_SCORE_THRESHOLD]
            if rejected:
                summary_lines.append("🗑️ <b>Principais rejeições da IA:</b>")
                for sj in rejected[:8]:
                    reason = str(sj.red_flags) if sj.red_flags and sj.red_flags != "None" else str(sj.fit_reason)
                    summary_lines.append(f"• <b>{sj.job.company}</b>: <i>{reason[:70]}...</i>")
        else:
            summary_lines.append("⚠️ Nenhuma vaga passou no filtro de afinidade inicial (RAG).")
                
        summary_lines.append("\n💾 <i>Lembrete: TODAS as vagas foram salvas no /stats</i>")
        try:
            send_telegram_message("\n".join(summary_lines))
        except Exception as e:
            logger.error(f"Failed to send summary: {e}")
                
        return {
            "total": len(all_scored),
            "good_matches": len(good_matches),
            "notified": notified,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        import traceback
        err_stack = traceback.format_exc()
        logger.error(f"FATAL PIPELINE ERROR: {e}\n{err_stack}")
        try:
            err_msg = f"❌ <b>Erro Crítico no Pipeline:</b>\n<pre>{err_stack[-1000:]}</pre>"
            send_telegram_message(err_msg)
        except:
            pass
        return {"total": 0, "good_matches": 0, "notified": False, "error": str(e)}


def _format_telegram_message(scored_jobs: list, total: int = 0) -> str:
    """Format jobs for Telegram with LLM insights."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    count = len(scored_jobs)
    
    lines = [
        f"🎯 <b>JobHunter — {count} vagas recomendadas!</b>",
        f"📅 {now}",
        "",
    ]
    
    for i, sj in enumerate(scored_jobs):
        job = sj.job
        
        # Verdict emoji
        verdict_map = {"APPLY": "✅", "MAYBE": "🟡", "SKIP": "❌"}
        verdict_emoji = verdict_map.get(sj.verdict, "❓")
        
        # Company tier emoji
        tier_map = {"Large": "🏢", "Mid": "🏬", "Startup": "🚀", "Consulting": "📋"}
        tier_emoji = tier_map.get(sj.company_tier, "❓")
        
        lines.append(f"{'━' * 28}")
        lines.append(f"{verdict_emoji} <b>#{i+1} — LLM: {sj.llm_score}% | RAG: {sj.score:.0f}%</b>")
        lines.append(f"💼 {job.title}")
        lines.append(f"{tier_emoji} {job.company} ({sj.company_tier})")
        lines.append(f"📍 {job.location}")
        
        if sj.seniority and sj.seniority != "Unknown":
            lines.append(f"📊 Nível: {sj.seniority}")
        
        if sj.fit_reason:
            lines.append(f"💡 {sj.fit_reason}")
        
        if sj.red_flags and sj.red_flags != "None":
            lines.append(f"⚠️ {sj.red_flags}")
        
        # Warn user when description was not available (LinkedIn blocking)
        if not job.description or len(job.description.strip()) < 50:
            lines.append("🔍 <i>Descrição não disponível — confira o link antes de aplicar</i>")
        
        if job.url:
            lines.append(f"🔗 <a href=\"{job.url}\">👉 Ver vaga completa</a>")
        
        lines.append("")
    
    lines.append(f"{'━' * 28}")
    lines.append(f"📊 Total analisado: {total} vagas")
    lines.append(f"⚡ Powered by JobHunter + Gemini AI")
    
    return "\n".join(lines)


def _format_telegram_message_from_db(jobs: list[dict], total: int = 0) -> str:
    """Format jobs from DB rows (dicts) for Telegram."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    count = len(jobs)
    
    lines = [
        f"🎯 <b>JobHunter — {count} vagas novas!</b>",
        f"📅 {now}",
        "",
    ]
    
    for i, j in enumerate(jobs):
        verdict_map = {"APPLY": "✅", "MAYBE": "🟡", "SKIP": "❌"}
        verdict_emoji = verdict_map.get(j.get("verdict", ""), "❓")
        
        tier_map = {"Large": "🏢", "Mid": "🏬", "Startup": "🚀", "Consulting": "📋"}
        tier_emoji = tier_map.get(j.get("company_tier", ""), "❓")
        
        lines.append(f"{'━' * 28}")
        lines.append(f"{verdict_emoji} <b>#{i+1} — LLM: {j.get('llm_score', 0)}% | RAG: {j.get('rag_score', 0):.0f}%</b>")
        lines.append(f"💼 {j.get('title', '')}")
        lines.append(f"{tier_emoji} {j.get('company', '')} ({j.get('company_tier', '')})")
        lines.append(f"📍 {j.get('location', '')}")
        
        seniority = j.get("seniority", "")
        if seniority and seniority != "Unknown":
            lines.append(f"📊 Nível: {seniority}")
        
        fit = j.get("fit_reason", "")
        if fit:
            lines.append(f"💡 {fit}")
        
        red_flags = j.get("red_flags", "")
        if red_flags and red_flags.lower() != "none":
            lines.append(f"⚠️ {red_flags}")
        
        # Warn user when description was not available (LinkedIn blocking)
        desc = j.get("description", "") or ""
        if len(desc.strip()) < 50:
            lines.append("🔍 <i>Descrição não disponível — confira o link antes de aplicar</i>")
        
        url = j.get("url", "")
        if url:
            lines.append(f'🔗 <a href="{url}">👉 Ver vaga completa</a>')
        
        lines.append("")
    
    lines.append(f"{'━' * 28}")
    lines.append(f"📊 Total analisado: {total} vagas")
    lines.append(f"⚡ Powered by JobHunter + Gemini AI")
    
    return "\n".join(lines)


def _print_classified_results(scored_jobs: list, show_top: int = 10):
    """Print classified results to console."""
    if not scored_jobs:
        print("\nNo matching jobs found.")
        return
    
    print(f"\n{'=' * 70}")
    print(f"  🏆 TOP {min(show_top, len(scored_jobs))} JOB MATCHES (LLM Classified)")
    print(f"{'=' * 70}")
    
    for i, sj in enumerate(scored_jobs[:show_top]):
        print(f"\n{'─' * 70}")
        print(f"  #{i + 1} | RAG: {sj.score:.0f}% | LLM: {sj.llm_score}% | {sj.verdict}")
        print(f"  💼 {sj.job.title}")
        print(f"  🏢 {sj.job.company} ({sj.company_tier}) | {sj.seniority}")
        print(f"  📍 {sj.job.location}")
        print(f"  💡 {sj.fit_reason}")
        if sj.red_flags and sj.red_flags != "None":
            print(f"  ⚠️  {sj.red_flags}")
        if sj.job.url:
            print(f"  🔗 {sj.job.url}")


def _save_results_csv(scored_jobs: list):
    """Save results to CSV with LLM data."""
    from pathlib import Path
    import csv
    
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = output_dir / f"jobs_{today}.csv"
    
    file_exists = filepath.exists()
    
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        
        if not file_exists:
            writer.writerow([
                "timestamp", "rag_score", "llm_score", "verdict",
                "career_path", "seniority", "company_tier",
                "title", "company", "location", "source", "url",
                "fit_reason", "red_flags",
            ])
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        for sj in scored_jobs:
            writer.writerow([
                timestamp,
                f"{sj.score:.1f}",
                sj.llm_score,
                sj.verdict,
                sj.career_path,
                sj.seniority,
                sj.company_tier,
                sj.job.title,
                sj.job.company,
                sj.job.location,
                sj.job.source,
                sj.job.url,
                sj.fit_reason,
                sj.red_flags,
            ])
    
    print(f"📄 Results saved to: {filepath}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    result = run_pipeline()
