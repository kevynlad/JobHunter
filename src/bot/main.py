"""
CareerBot — Main Entry Point

Starts the Telegram bot with long polling.
The bot runs continuously, listening for messages and button clicks.

Run locally:
    python -m src.bot.main

Deploy on Railway/Render:
    The same command via Procfile or railway.toml
"""
import logging
import os

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from src.bot.handlers import handle_message, handle_start, handle_callback
from src.bot.triggers import setup_triggers
from src.jobs.database import init_db

load_dotenv()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set! Check your .env file.")

    # Ensure DB is initialized with the updated schema
    init_db()

    app = Application.builder().token(token).build()

    # Handlers — order matters: specific before generic
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Proactive triggers (follow-ups, weekly digest)
    setup_triggers(app.job_queue)

    logger.info("🤖 CareerBot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
