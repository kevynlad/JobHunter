"""
CareerBot — Proactive Triggers

Scheduled jobs that run automatically to keep the user informed:

1. Follow-up trigger (every 6h): reminds about jobs marked as 'interested'
   for 3+ days with no application
2. Weekly digest (every Monday 9am): top unprocessed jobs from the past week
3. Interview tracker (every 3 days): checks if there's been any update on 
   'interviewing' status jobs

These run inside the python-telegram-bot JobQueue, which is powered
by APScheduler. No external cron needed when running locally.
For GitHub Actions, a separate workflow handles these triggers.
"""
import os
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from telegram.ext import CallbackContext

from src.bot.keyboards import applied_followup_keyboard


DB_PATH = Path(__file__).parent.parent.parent / "data" / "jobs.db"
CHAT_ID_ENV = "TELEGRAM_CHAT_ID"  # fallback when no multi-user registry


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _get_chat_id() -> int | None:
    cid = os.getenv(CHAT_ID_ENV, "")
    return int(cid) if cid else None


# ─────────────────────────── TRIGGER FUNCTIONS ───────────────────────────

async def followup_trigger(context: CallbackContext):
    """
    Sent every 6 hours.
    Finds jobs marked 'interested' for 3+ days with no application.
    Sends a gentle reminder with action buttons.
    """
    chat_id = _get_chat_id()
    if not chat_id:
        return

    cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    conn = _get_db()
    rows = conn.execute("""
        SELECT job_id, title, company, combined_score
        FROM jobs
        WHERE status = 'interested'
        AND first_seen <= ?
        ORDER BY combined_score DESC
        LIMIT 5
    """, (cutoff,)).fetchall()
    conn.close()

    if not rows:
        return

    for row in rows:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⏰ <b>Lembrete de vaga!</b>\n\n"
                f"Você marcou interesse em:\n"
                f"💼 <b>{row['title']}</b> — {row['company']}\n\n"
                f"Já aplicou? O que acha?"
            ),
            parse_mode="HTML",
            reply_markup=applied_followup_keyboard(row["job_id"]),
        )


async def weekly_digest(context: CallbackContext):
    """
    Sent every Monday at 9am.
    Top 5 jobs from the past week that were not yet acted upon.
    """
    chat_id = _get_chat_id()
    if not chat_id:
        return

    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    conn = _get_db()
    rows = conn.execute("""
        SELECT job_id, title, company, llm_score, rag_score, verdict, fit_reason
        FROM jobs
        WHERE first_seen >= ?
        AND status IN ('NEW', 'interested')
        ORDER BY llm_score DESC, rag_score DESC
        LIMIT 5
    """, (cutoff,)).fetchall()
    conn.close()

    if not rows:
        await context.bot.send_message(
            chat_id=chat_id,
            text="📊 <b>Digest Semanal</b>\n\nNenhuma vaga nova essa semana. O pipeline continua monitorando! 🔍",
            parse_mode="HTML",
        )
        return

    lines = [
        "📊 <b>Digest Semanal — Top Vagas da Semana</b>\n",
        f"Encontrei <b>{len(rows)} vagas</b> não aplicadas nos últimos 7 dias:\n",
    ]
    for i, row in enumerate(rows, 1):
        verdict_map = {"APPLY": "✅", "MAYBE": "🟡", "SKIP": "❌"}
        v = verdict_map.get(row["verdict"], "❓")
        lines.append(
            f"{v} <b>#{i} — {row['title']}</b> @ {row['company']}\n"
            f"   LLM: {row['llm_score']}% | RAG: {row['rag_score']:.0f}%\n"
        )

    lines.append("\nEscreva o nome de uma empresa para saber mais ou gerar uma cover letter! 💬")
    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="HTML",
    )


# ─────────────────────────── SETUP ───────────────────────────

def setup_triggers(job_queue):
    """Register all proactive triggers with the APScheduler job queue."""
    # Follow-up: every 6 hours
    job_queue.run_repeating(
        followup_trigger,
        interval=6 * 3600,
        first=60,  # First run 60s after bot starts
        name="followup_trigger",
    )

    # Weekly digest: every Monday at 9am
    job_queue.run_daily(
        weekly_digest,
        time=datetime.strptime("09:00", "%H:%M").time(),
        days=(0,),  # Monday only
        name="weekly_digest",
    )
