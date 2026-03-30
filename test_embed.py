import os
import httpx
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_FREE_API_KEY")

url = f"https://generativelanguage.googleapis.com/v1/models/text-embedding-004:embedContent?key={api_key}"
payload = {
    "model": "models/text-embedding-004",
    "content": {"parts": [{"text": "Hello world"}]}
}
print("Testing embedContent...")
resp = httpx.post(url, json=payload, timeout=10)
print(resp.status_code)
print(resp.text)

print("\nTesting batchEmbedContents...")
batch_url = f"https://generativelanguage.googleapis.com/v1/models/text-embedding-004:batchEmbedContents?key={api_key}"
batch_payload = {
    "requests": [
        {"model": "models/text-embedding-004", "content": {"parts": [{"text": "Hello"}]}}
    ]
}
resp2 = httpx.post(batch_url, json=batch_payload, timeout=10)
print(resp2.status_code)
print(resp2.text)
