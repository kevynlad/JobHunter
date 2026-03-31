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

from src.bot.handlers import (
    handle_message,
    handle_callback,
    handle_pipeline_command,
    handle_stats_command,
    handle_debug_command,
)
from src.bot.onboarding import handle_start, handle_set_key, handle_set_profile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the user of a failure."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_html(
                "⚠️ <b>Ops! Tive um problema interno.</b>\n"
                "Pode ter sido um _timeout_ na API do Gemini ou erro de conexão. "
                "Por favor, tente novamente em alguns instantes."
            )
        except Exception:
            pass

load_dotenv()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class HealthcheckHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP server to satisfy Railway's port binding healthcheck."""
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"CareerBot V2 is running")

def run_healthcheck_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthcheckHandler)
    logger.info(f"🌐 HTTP Healthcheck Server running on port {port}")
    server.serve_forever()


def create_app() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set! Check sua chave no .env.")

    app = Application.builder().token(token).build()

    # Handlers — order matters: specific before generic
    app.add_handler(CommandHandler("start",       handle_start))
    app.add_handler(CommandHandler("set_key",     handle_set_key))
    app.add_handler(CommandHandler("set_profile", handle_set_profile))
    app.add_handler(CommandHandler("pipeline",    handle_pipeline_command))
    app.add_handler(CommandHandler("stats",       handle_stats_command))
    app.add_handler(CommandHandler("debug",       handle_debug_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Global Error Handler para capturar timeouts da Vercel ou falhas do Gemini
    app.add_error_handler(error_handler)

    # Proactive triggers migrated to GitHub Actions worker (scripts/github_worker.py)
    # setup_triggers was removed — follow-ups are handled by the background cron job.

    return app


def main():
    """Local Testing Entrypoint with Long Polling"""
    logger.info("Starting local polling... (Not for Vercel/Serverless)")
    
    # Start the HTTP server in a background thread for Railway healthcheck (Legacy)
    port = int(os.getenv("PORT", 8080))
    if os.getenv("RAILWAY_ENVIRONMENT"):
        threading.Thread(target=run_healthcheck_server, daemon=True).start()

    app = create_app()

    logger.info("🤖 CareerBot is running natively. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
