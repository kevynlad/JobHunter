import os
import sys
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application

# Ensure the root of the project is in the PYTHOPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot.main import create_app

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global ptb application
ptb_app: Application = None

@asynccontextmanager
async def lifespan(_app: FastAPI):
    global ptb_app
    # Initializing python-telegram-bot application
    try:
        ptb_app = create_app()
        await ptb_app.initialize()
        await ptb_app.start()
        logger.info("Bot application initialized on Vercel.")
    except Exception as e:
        logger.error(f"Failed to initialize bot: {e}")
    
    yield
    
    # Shutdown
    if ptb_app:
        await ptb_app.stop()
        await ptb_app.shutdown()
        logger.info("Bot application shut down.")

# Initialize FastAPI
app = FastAPI(lifespan=lifespan)


@app.post("/api/webhook")
async def telegram_webhook(req: Request):
    """
    Endpoint that Telegram will hit with updates.
    """
    global ptb_app
    if not ptb_app:
        logger.error("PTB App is not initialized.")
        return Response(status_code=500, content="Application not initialized")
    
    try:
        # We need the bot object to deserialize the Update
        data = await req.json()
        update = Update.de_json(data, ptb_app.bot)
        
        # Feed the update into the application
        await ptb_app.process_update(update)
        
        return Response(status_code=200, content="OK")
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
        # Even if there's an internal error, return 200 so Telegram stops retrying the bad payload
        return Response(status_code=200, content="Internal Error Acknowledged")

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "JobHunter Vercel Webhook API is running."}

@app.get("/")
async def root():
    return {"status": "ok", "service": "JobHunter V2 webhook API"}
