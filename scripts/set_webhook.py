"""
Script to register your Vercel URL with Telegram.
Usage: python scripts/set_webhook.py https://your-project.vercel.app/api/webhook
"""
import sys
import os
import requests
from dotenv import load_dotenv

def main():
    # Load .env variables
    load_dotenv()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN is missing from .env")
        sys.exit(1)
        
    if len(sys.argv) < 2:
        print("❌ Error: Missing webhook URL.")
        print("Usage: python scripts/set_webhook.py https://your-domain.vercel.app/api/webhook")
        sys.exit(1)
        
    webhook_url = sys.argv[1].strip()
    
    # Optional: Verify if it looks like an HTTPS URL
    if not webhook_url.startswith("https://"):
        print("⚠️ Warning: Telegram webhooks REQUIRE https://")
        
    api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    
    print(f"🔄 Setting webhook to: {webhook_url}")
    try:
        response = requests.post(api_url, json={"url": webhook_url})
        data = response.json()
        
        if data.get("ok"):
            print("✅ Webhook set successfully!")
            print(f"Telegram will now POST updates to {webhook_url}")
        else:
            print(f"❌ Failed to set webhook. Telegram says: {data}")
    except Exception as e:
        print(f"❌ Network error while setting webhook: {e}")

if __name__ == "__main__":
    main()
