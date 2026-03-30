import os
import httpx
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_FREE_API_KEY")

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
resp = httpx.get(url)
models = resp.json().get("models", [])
for m in models:
    if "embed" in m["name"].lower() or "004" in m["name"].lower():
        print(f"Name: {m['name']} | Supported Methods: {m.get('supportedGenerationMethods', [])}")
