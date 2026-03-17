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
from src.jobs.database import init_db, DB_PATH
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

load_dotenv()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class SyncHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP server to receive DB syncs from the pipeline."""
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"CareerBot is running")
        
    def do_POST(self):
        if self.path != '/sync':
            self.send_response(404)
            self.end_headers()
            return
            
        token = self.headers.get('Authorization')
        expected = os.getenv('SYNC_TOKEN')
        if not expected or token != f"Bearer {expected}":
            self.send_response(401)
            self.end_headers()
            return
            
        length = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(length)
        
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DB_PATH, "wb") as f:
            f.write(data)
            
        logger.info(f"✅ Received synchronized jobs.db ({len(data)} bytes)")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"Synced {len(data)} bytes".encode())

def run_sync_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SyncHandler)
    logger.info(f"🌐 HTTP Sync Server running on port {port}")
    server.serve_forever()


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set! Check your .env file.")

    # Start the HTTP server in a background thread for Railway healthcheck + DB syncing
    threading.Thread(target=run_sync_server, daemon=True).start()

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
