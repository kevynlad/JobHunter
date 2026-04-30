
import os
import sys
import logging
import json
from datetime import datetime
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import httpx

# Configure logging to stdout
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Diagnostic")

load_dotenv()

def test_gemini_key(api_key, label="System"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": "Hello"}]}]}
    try:
        resp = httpx.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"✅ {label} Key: Valid")
            return True
        else:
            print(f"❌ {label} Key: Invalid (Status {resp.status_code})")
            print(f"   Response: {resp.text}")
            return False
    except Exception as e:
        print(f"❌ {label} Key: Connection Error: {e}")
        return False

def diagnostic():
    print("\n" + "="*60)
    print("🔍 JOBHUNTER PIPELINE DIAGNOSTIC")
    print("="*60)

    # 1. Check Master Key
    master_key = os.getenv("ENCRYPTION_MASTER_KEY")
    if not master_key:
        print("❌ ENCRYPTION_MASTER_KEY: Missing")
    else:
        print(f"✅ ENCRYPTION_MASTER_KEY: Present (len={len(master_key)})")
        try:
            Fernet(master_key.encode())
            print("✅ ENCRYPTION_MASTER_KEY: Valid Fernet format")
        except Exception as e:
            print(f"❌ ENCRYPTION_MASTER_KEY: Invalid Format: {e}")

    # 2. Check Database Connection
    from src.db.client import get_client
    try:
        client = get_client()
        # Test a simple query
        res = client.table("users").select("count", count="exact").limit(1).execute()
        print(f"✅ Supabase Connection: Success (Found {res.count} users)")
    except Exception as e:
        print(f"❌ Supabase Connection: Failed: {e}")

    # 3. Check System Keys
    free_key = os.getenv("GEMINI_FREE_API_KEY")
    paid_key = os.getenv("GEMINI_PAID_API_KEY")
    pool = os.getenv("GEMINI_API_KEYS")

    if free_key: test_gemini_key(free_key, "System FREE")
    if paid_key: test_gemini_key(paid_key, "System PAID")
    
    if pool:
        keys = [k.strip() for k in pool.split(",") if k.strip()]
        print(f"ℹ️ Found {len(keys)} keys in GEMINI_API_KEYS pool")
        for i, k in enumerate(keys):
            test_gemini_key(k, f"Pool Key #{i+1}")

    # 4. Check Active Users Keys
    from src.db.users import get_active_users
    try:
        active_users = get_active_users()
        print(f"ℹ️ Found {len(active_users)} active users in DB")
        for user in active_users:
            u_id = user["user_id"]
            u_name = user.get("first_name", "Unknown")
            print(f"\n--- Testing keys for User: {u_name} ({u_id}) ---")
            
            if user.get("gemini_free_key"):
                test_gemini_key(user["gemini_free_key"], f"User {u_id} FREE")
            else:
                print(f"⚠️ User {u_id}: No FREE key")
                
            if user.get("gemini_paid_key"):
                test_gemini_key(user["gemini_paid_key"], f"User {u_id} PAID")
    except Exception as e:
        print(f"❌ Error checking active users: {e}")

if __name__ == "__main__":
    diagnostic()
