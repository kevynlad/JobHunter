import asyncio
import os
import sys
from dotenv import load_dotenv
from google import genai

sys.stdout.reconfigure(encoding='utf-8')

async def list_models():
    load_dotenv()
    api_keys = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", "")).split(",")
    key = api_keys[0].strip()
    
    client = genai.Client(api_key=key)
    
    print("Available models:")
    try:
        client_sync = genai.Client(api_key=key)
        for m in client_sync.models.list():
            if "flash" in m.name:
                print(m.name)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(list_models())
