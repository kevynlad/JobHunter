import os
from google import genai
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("GEMINI_FREE_API_KEY")
client = genai.Client(api_key=key)
try:
    print("Testing text-embedding-004...")
    r = client.models.embed_content(model="text-embedding-004", contents="hello")
    print("Success text-embedding-004!")
except Exception as e:
    print("Error:", e)

try:
    print("Testing text-embedding-004 (with models/)...")
    r = client.models.embed_content(model="models/text-embedding-004", contents="hello")
    print("Success models/text-embedding-004!")
except Exception as e:
    print("Error:", e)

try:
    print("Testing gemini-embedding-001...")
    r = client.models.embed_content(model="gemini-embedding-001", contents="hello")
    print("Success gemini-embedding-001!")
except Exception as e:
    print("Error:", e)

try:
    print("Testing gemini-embedding-2-preview...")
    r = client.models.embed_content(model="gemini-embedding-2-preview", contents="hello")
    print("Success gemini-embedding-2-preview!")
except Exception as e:
    print("Error:", e)
