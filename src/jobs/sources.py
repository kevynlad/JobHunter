"""
=============================================================
🌐 SOURCES.PY — Job Search API Integrations (Brazil-focused)
=============================================================

WHAT DOES THIS FILE DO?
-----------------------
This file connects to job APIs to find real job postings.
We use TWO sources:

1. JSearch (RapidAPI) — aggregates LinkedIn + Indeed + Glassdoor
   → Free tier: 200 requests/month
   → Supports Brazil location + date filter

2. Arbeitnow — aggregates Greenhouse job boards
   → Free, no API key needed
   → Mostly European but some global roles

HOW IT WORKS:
  Your code calls search() → we call the API → 
  API returns JSON → we convert to JobPosting objects

=============================================================
"""

import hashlib
from datetime import datetime

import httpx
import pandas as pd
from jobspy import scrape_jobs

from src.jobs.models import JobPosting


# ----- CONFIGURATION -----
REQUEST_TIMEOUT = 60
USER_AGENT = "JobHunter/0.1 (automated job search tool)"


def _make_id(source: str, raw_id: str) -> str:
    """Create a unique ID for a job, combining source name and API id."""
    return f"{source}_{raw_id}"


# =============================================================
# SOURCE 1: JSEARCH (RapidAPI)
# 
# This is our MAIN source. It aggregates jobs from:
#   - LinkedIn
#   - Indeed
#   - Glassdoor
#   - ZipRecruiter
#   - and many more
#
# Free tier: 200 requests/month (no credit card needed)
# API docs: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
# =============================================================

class JobSpySource:
    name = "jobspy"
    
    def search(
        self,
        query: str,
        location: str = "",
        limit: int = 10,
        days_old: int = 7,
        remote_only: bool = False,
    ) -> list[JobPosting]:
        
        try:
            jobs_df = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=query,
                location=location,
                results_wanted=limit,
                hours_old=days_old * 24,
                country_linkedin="brazil",
                is_remote=remote_only,
                linkedin_fetch_description=True,  # Fetch full job description from LinkedIn
            )
            
            if jobs_df.empty:
                return []
                
            jobs = []
            for _, row in jobs_df.iterrows():
                job_id = f"jobspy_{row.get('id', hash(row.get('title', '')))}"
                
                # Sanitize description: pandas NaN becomes "nan" via str()
                raw_desc = row.get('description', '')
                description = '' if pd.isna(raw_desc) else str(raw_desc).strip()
                
                jobs.append(JobPosting(
                    id=job_id,
                    title=str(row.get('title', 'Unknown')),
                    company=str(row.get('company', 'Unknown')),
                    location=str(row.get('location', 'Not specified')),
                    url=str(row.get('job_url', '')),
                    description=description,
                    source=f"jobspy ({row.get('site', 'unknown')})",
                    posted_at=str(row.get('date_posted', datetime.now().date())),
                    tags=[]
                ))
            
            return jobs
            
        except Exception as e:
            print(f"  [!] JobSpy error: {e}")
            return []


# =============================================================
# HELPER: Get all sources
# =============================================================

def get_all_sources(rapidapi_key: str = "") -> list:
    """Get all configured job sources."""
    return [
        JobSpySource(),                       # LinkedIn + Indeed + Glassdoor + ZipRecruiter
    ]


# Quick test
if __name__ == "__main__":
    import sys
    import os
    from dotenv import load_dotenv
    
    sys.stdout.reconfigure(encoding='utf-8')
    load_dotenv()
    
    api_key = os.getenv("RAPIDAPI_KEY", "")
    
    print("=" * 60)
    print("  JOB SEARCH — Testing APIs")
    print("=" * 60)
    
    # Test JSearch
    print("\n--- Testing JobSpy (LinkedIn+Indeed+Glassdoor) ---")
    jobspy = JobSpySource()
    jobs = jobspy.search("Product Manager", location="São Paulo, Brazil", limit=3, days_old=7)
    print(f"Found {len(jobs)} jobs:")
    for job in jobs:
        print(f"  - {job.title} at {job.company}")
        print(f"    Location: {job.location} | Source: {job.source}")
        print(f"    URL: {job.url}")
        print()
