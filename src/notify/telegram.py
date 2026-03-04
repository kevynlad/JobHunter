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
