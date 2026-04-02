import os
import socket
import sys
import urllib.parse

def check_env():
    print("=" * 60)
    print("   🔍 JOBHUNTER PIPELINE DIAGNOSTIC REPORT")
    print("=" * 60)
    
    # 1. Environment Variables Check (existence only)
    required_vars = [
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "ENCRYPTION_MASTER_KEY",
        "TELEGRAM_BOT_TOKEN",
        "GEMINI_API_KEYS",
        "TARGET_USER_ID"
    ]
    
    print("\n[Section 1: Environment Variables]")
    for var in required_vars:
        val = os.environ.get(var, "")
        status = "✅ DEFINED" if val else "❌ MISSING"
        # Check if it looks truncated or suspicious
        detail = f" (length: {len(val)})" if val else ""
        print(f"  {var:25}: {status}{detail}")

    # 2. Database Connectivity Test
    print("\n[Section 2: Database Connectivity]")
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if db_url:
        try:
            # Parse URL to get host and port
            up_result = urllib.parse.urlparse(db_url)
            host = up_result.hostname
            port = up_result.port or 5432
            
            print(f"  Connecting to: {host}:{port}...")
            
            # Simple TCP socket check
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((host, port))
            s.close()
            print("  ✅ TCP Connection successful!")
        except Exception as e:
            print(f"  ❌ Connection failed: {e}")
    else:
        print("  ⚠️ Skipped: No DATABASE_URL found.")

    # 3. DNS / Networking Check
    print("\n[Section 3: DNS & Networking]")
    test_hosts = ["api.telegram.org", "generativelanguage.googleapis.com", "google.com"]
    for host in test_hosts:
        try:
            ip = socket.gethostbyname(host)
            print(f"  ✅ Resolved {host:35} to {ip}")
        except Exception as e:
            print(f"  ❌ Could not resolve {host}: {e}")

    print("\n" + "=" * 60)
    print("   📊 END OF DIAGNOSTIC")
    print("=" * 60)

if __name__ == "__main__":
    check_env()
