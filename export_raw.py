import sys
import os
from pathlib import Path
import csv
from datetime import datetime

# Add root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from src.jobs.matcher import search_and_match

def export_raw_jobs():
    print("⏳ Scraping jobs (this may take a minute or two)...")
    all_scored = search_and_match(min_score=0)
    
    if not all_scored:
        print("❌ No jobs found.")
        return
        
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    filepath = output_dir / "raw_jobs_for_review.csv"
    
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Index", "RAG_Score", "Title", "Company", "Location", "Source", "URL"])
        
        for i, sj in enumerate(all_scored):
            writer.writerow([
                i + 1,
                f"{sj.score:.1f}",
                sj.job.title,
                sj.job.company,
                sj.job.location,
                sj.job.source,
                sj.job.url
            ])
            
    print(f"✅ Successfully exported {len(all_scored)} raw jobs to {filepath}")
    print("Open this file in Excel or Google Sheets to review the actual scraped jobs.")

if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    export_raw_jobs()
