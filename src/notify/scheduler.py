"""
=============================================================
⏰ SCHEDULER.PY — Schedule JobHunter to Run 2x/Day
=============================================================

WHAT DOES THIS FILE DO?
-----------------------
This script keeps running in the background and executes the
pipeline at scheduled times (default: 8:00 AM and 6:00 PM).

HOW TO USE:
-----------
Option 1 (simple): Run this script and keep the terminal open
    python -m src.notify.scheduler

Option 2 (better): Use Windows Task Scheduler
    See the setup instructions printed when running this file.

HOW SCHEDULING WORKS (for beginners):
-------------------------------------
The script runs an infinite loop:
    1. Check the current time
    2. If it's a scheduled time → run the pipeline
    3. Sleep for 5 minutes
    4. Repeat

It's like setting an alarm clock that runs a program.

=============================================================
"""

import sys
import time
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()


# ----- SCHEDULE CONFIGURATION -----
# Times to run the pipeline (24h format)
SCHEDULE_TIMES = [
    (8, 0),    # 8:00 AM
    (18, 0),   # 6:00 PM
]

# How often to check if it's time to run (seconds)
CHECK_INTERVAL = 300  # 5 minutes


def _should_run_now(last_run: datetime | None) -> bool:
    """
    Check if it's time to run the pipeline.
    
    Returns True if:
    - Current time matches a scheduled time (within 5 min window)
    - We haven't already run in the last 30 minutes
    """
    now = datetime.now()
    
    # Don't run if we ran less than 30 minutes ago
    if last_run and (now - last_run) < timedelta(minutes=30):
        return False
    
    # Check if current time matches any schedule
    for hour, minute in SCHEDULE_TIMES:
        scheduled = now.replace(hour=hour, minute=minute, second=0)
        diff = abs((now - scheduled).total_seconds())
        
        # Within 5-minute window of scheduled time
        if diff < CHECK_INTERVAL:
            return True
    
    return False


def run_scheduler():
    """
    Run the scheduler loop.
    Keeps running until you close the terminal.
    """
    print("=" * 60)
    print("  ⏰ JobHunter Scheduler")
    print("=" * 60)
    print(f"\n  Schedule: {', '.join(f'{h:02d}:{m:02d}' for h, m in SCHEDULE_TIMES)}")
    print(f"  Check interval: every {CHECK_INTERVAL // 60} minutes")
    print(f"  Press Ctrl+C to stop\n")
    
    last_run = None
    
    while True:
        now = datetime.now()
        
        if _should_run_now(last_run):
            print(f"\n{'=' * 60}")
            print(f"  🔔 Scheduled run at {now.strftime('%H:%M')}")
            print(f"{'=' * 60}")
            
            try:
                from src.pipeline import run_pipeline
                result = run_pipeline()
                last_run = datetime.now()
                
                print(f"\n  Next check in {CHECK_INTERVAL // 60} minutes...")
            except Exception as e:
                print(f"\n  ❌ Pipeline error: {e}")
                import traceback
                traceback.print_exc()
        else:
            # Show a heartbeat every check
            next_times = []
            for h, m in SCHEDULE_TIMES:
                t = now.replace(hour=h, minute=m, second=0)
                if t < now:
                    t += timedelta(days=1)
                next_times.append(t)
            
            next_run = min(next_times)
            time_until = next_run - now
            hours_left = time_until.seconds // 3600
            mins_left = (time_until.seconds % 3600) // 60
            
            print(f"  [{now.strftime('%H:%M')}] Waiting... next run in {hours_left}h {mins_left}m", end="\r")
        
        time.sleep(CHECK_INTERVAL)


def print_task_scheduler_instructions():
    """Print instructions for setting up Windows Task Scheduler."""
    python_path = sys.executable
    project_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    print("""
╔══════════════════════════════════════════════════════════╗
║  📋 Windows Task Scheduler Setup (Recommended)          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  Instead of keeping a terminal open, you can use         ║
║  Windows Task Scheduler to run the pipeline              ║
║  automatically at 8:00 AM and 6:00 PM.                   ║
║                                                          ║
║  Steps:                                                  ║
║  1. Press Win+R → type 'taskschd.msc' → Enter            ║
║  2. Click 'Create Basic Task...'                         ║
║  3. Name: 'JobHunter Morning' (or Evening)               ║
║  4. Trigger: Daily, at 08:00 (or 18:00)                  ║
║  5. Action: Start a program                              ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")
    print(f"  Program/script:")
    print(f"    {python_path}")
    print(f"\n  Arguments:")
    print(f"    -m src.pipeline")
    print(f"\n  Start in:")
    print(f"    {project_path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    
    if "--setup" in sys.argv:
        print_task_scheduler_instructions()
    else:
        print("\n  Tip: Run with --setup to see Windows Task Scheduler instructions\n")
        run_scheduler()
