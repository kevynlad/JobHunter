"""
=============================================================
📱 TELEGRAM.PY — Telegram Bot Notifications
=============================================================

WHAT DOES THIS FILE DO?
-----------------------
Sends job notification messages to your Telegram.

When the system finds good job matches (≥5 jobs at 70%+), it
formats them into a nice message and sends it to your bot.

HOW TELEGRAM BOTS WORK (for beginners):
---------------------------------------
1. You created a bot with BotFather → got a TOKEN
2. You sent the bot a message → we got your CHAT_ID
3. Now we can send messages TO you using:
   POST https://api.telegram.org/bot<TOKEN>/sendMessage
   
It's just an HTTP request — same as how we call job APIs!

=============================================================
"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()


def _inline_keyboard(job_id: str) -> dict:
    """Build the inline keyboard payload for a job card."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Quero Aplicar", "callback_data": f"apply:{job_id}"},
                {"text": "📝 Cover Letter", "callback_data": f"cover:{job_id}"},
            ],
            [
                {"text": "⏰ Lembrar em 3 dias", "callback_data": f"remind:{job_id}"},
                {"text": "❌ Não interessa", "callback_data": f"skip:{job_id}"},
            ],
        ]
    }


def send_job_cards_with_buttons(jobs: list, total_analyzed: int = 0) -> bool:
    """
    Send one Telegram message per job card, each with action buttons.
    This replaces the old bulk-text notification with interactive per-job cards.
    
    Args:
        jobs: list of dicts with job_id, title, company, llm_score, rag_score,
              verdict, fit_reason, url, seniority, company_tier
        total_analyzed: total number of jobs scanned (for the header summary)
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("[!] Telegram: Missing BOT_TOKEN or CHAT_ID in .env")
        return False

    from datetime import datetime
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # 1. Send a summary header first
    count = len(jobs)
    header = (
        f"🎯 <b>JobHunter V2 — {count} vagas novas!</b>\n"
        f"📅 {now} | 📊 {total_analyzed} analisadas\n\n"
        f"Abaixo cada vaga com botões de ação 👇"
    )
    _raw_send(token, chat_id, header, keyboard=None)

    # 2. Send one card per job with buttons
    verdict_map = {"APPLY": "✅", "MAYBE": "🟡", "SKIP": "❌"}
    tier_map = {"Large": "🏢", "Mid": "🏬", "Startup": "🚀"}

    for i, j in enumerate(jobs):
        job_id = j.get("job_id", j.get("id", ""))
        v = verdict_map.get(j.get("verdict", ""), "❓")
        tier = tier_map.get(j.get("company_tier", ""), "🏬")
        seniority = j.get("seniority", "")
        fit = j.get("fit_reason", "")
        url = j.get("url", "")
        red_flags = j.get("red_flags", "")

        lines = [
            f"{v} <b>#{i+1} — LLM: {j.get('llm_score', 0)}% | RAG: {j.get('rag_score', 0):.0f}%</b>",
            f"💼 <b>{j.get('title', '')}</b>",
            f"{tier} {j.get('company', '')} | 📍 {j.get('location', '')}",
        ]
        if seniority and seniority != "Unknown":
            lines.append(f"📊 Nível: {seniority}")
        if fit:
            lines.append(f"💡 {fit[:200]}")
        if red_flags and red_flags.lower() not in ("none", ""):
            lines.append(f"⚠️ {red_flags[:100]}")
        if url:
            lines.append(f'🔗 <a href="{url}">Ver vaga completa</a>')

        card_text = "\n".join(lines)
        keyboard = _inline_keyboard(job_id) if job_id else None
        _raw_send(token, chat_id, card_text, keyboard=keyboard)

    return True


def _raw_send(token: str, chat_id: str, text: str, keyboard: dict | None) -> bool:
    """Send a single Telegram message, optionally with an inline keyboard."""
    payload = {
        "chat_id": chat_id,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=15)
        data = r.json()
        if not data.get("ok"):
            print(f"[!] Telegram error: {data.get('description', 'Unknown')}")
            return False
        return True
    except Exception as e:
        print(f"[!] Telegram error: {e}")
        return False


def send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a message to the user via Telegram.
    
    Args:
        text: The message text (supports HTML or Markdown formatting)
        parse_mode: "HTML" or "Markdown"
    
    Returns:
        True if sent successfully, False otherwise
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    
    if not token or not chat_id:
        print("[!] Telegram: Missing BOT_TOKEN or CHAT_ID in .env")
        return False
    
    try:
        # Telegram has a 4096 character limit per message
        # If our message is longer, we split it
        MAX_LENGTH = 4000
        
        if len(text) <= MAX_LENGTH:
            messages = [text]
        else:
            # Split by double newline (paragraph breaks)
            messages = _split_message(text, MAX_LENGTH)
        
        for msg in messages:
            response = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": msg,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,  # Don't show URL previews
                },
                timeout=15,
            )
            data = response.json()
            if not data.get("ok"):
                print(f"[!] Telegram error: {data.get('description', 'Unknown')}")
                return False
        
        return True
        
    except Exception as e:
        print(f"[!] Telegram error: {e}")
        return False


def _split_message(text: str, max_length: int) -> list[str]:
    """Split a long message into smaller chunks at paragraph breaks."""
    parts = []
    current = ""
    
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            parts.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    
    if current:
        parts.append(current)
    
    return parts


def format_job_notification(scored_jobs: list, total_found: int = 0) -> str:
    """
    Format scored jobs into a nice Telegram message.
    
    Uses HTML formatting because Telegram supports:
    <b>bold</b>, <i>italic</i>, <a href="url">link</a>, <code>code</code>
    """
    from datetime import datetime
    
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    count = len(scored_jobs)
    
    lines = [
        f"🎯 <b>JobHunter — {count} vagas encontradas!</b>",
        f"📅 {now}",
        "",
    ]
    
    for i, sj in enumerate(scored_jobs):
        job = sj.job
        score = sj.score
        
        # Score emoji
        if score >= 80:
            emoji = "🟢"
        elif score >= 70:
            emoji = "🟡"
        else:
            emoji = "🟠"
        
        # Company tier (if classified by LLM)
        tier = ""
        if hasattr(sj, "company_tier") and sj.company_tier:
            tier = f" | {sj.company_tier}"
        
        # Career path
        path = f" [{sj.career_path}]" if sj.career_path else ""
        
        lines.append(f"{'━' * 30}")
        lines.append(f"{emoji} <b>#{i+1} — {score:.0f}%</b>{path}")
        lines.append(f"💼 {job.title}")
        lines.append(f"🏢 {job.company}{tier}")
        lines.append(f"📍 {job.location}")
        
        if job.url:
            lines.append(f"🔗 <a href=\"{job.url}\">Aplicar</a>")
        
        lines.append("")
    
    # Footer
    lines.append(f"{'━' * 30}")
    if total_found > count:
        lines.append(f"📊 Total encontrado: {total_found} vagas")
        lines.append(f"📋 Mostrando: top {count} (score ≥70%)")
    lines.append(f"⚡ Powered by JobHunter RAG")
    
    return "\n".join(lines)


# Test when running directly
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    # Send a simple test message
    success = send_telegram_message(
        "🧪 <b>Test</b> — Telegram integration working!\n\n"
        "This is a test from JobHunter.\n"
        "If you see this, notifications are ready! ✅",
        parse_mode="HTML",
    )
    print(f"Test message sent: {success}")
