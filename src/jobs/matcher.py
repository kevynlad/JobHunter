"""
=============================================================
🎯 MATCHER.PY — Job Matching Engine (Brazil-focused)
=============================================================

WHAT DOES THIS FILE DO?
-----------------------
This is the BRAIN of the job search. It:

1. Reads your search config (career paths, locations, etc.)
2. Searches ALL sources for EACH career path
3. Removes duplicate postings
4. Scores each job against your career (using RAG)
5. Ranks everything — best matches first

The result: a ranked list of real jobs that match YOUR career,
organized by which career path they belong to.

=============================================================
"""

import sys
import os
from pathlib import Path

from dotenv import load_dotenv

from src.jobs.models import JobPosting, ScoredJob, SearchFilters
from src.jobs.sources import get_all_sources
from src.jobs.config import CAREER_PATHS, LOCATIONS, INCLUDE_REMOTE, MAX_DAYS_OLD, RESULTS_PER_QUERY, MIN_MATCH_SCORE
from src.rag.retriever import score_job


# Load environment variables
load_dotenv()


def _normalize_text(text: str) -> str:
    """Normalize text for duplicate detection."""
    return " ".join(text.lower().strip().split())


def _deduplicate_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    """
    Remove duplicate job postings.
    Same title + company = duplicate.
    """
    seen = set()
    unique = []
    for job in jobs:
        fp = f"{_normalize_text(job.title)}|{_normalize_text(job.company)}"
        if fp not in seen:
            seen.add(fp)
            unique.append(job)
    return unique


def search_career_path(
    career_path: dict,
    sources: list,
    days_old: int = 7,
) -> list[JobPosting]:
    """
    Search all sources for ONE career path.
    
    For example, for "Product" career path, we search:
      "Product Manager in São Paulo, Brazil"
      "Product Owner in São Paulo, Brazil"
      "Product Manager in Brazil" (remote)
      etc.
    """
    path_name = career_path["name"]
    queries = career_path["queries"]
    all_jobs: list[JobPosting] = []
    
    print(f"\n  📂 Career Path: {path_name}")
    print(f"  {'─' * 50}")
    
    for query in queries:
        for location in LOCATIONS:
            for source in sources:
                label = f"    {source.name} → \"{query}\" in {location}"
                print(f"{label}...", end=" ")
                
                jobs = source.search(
                    query=query,
                    location=location,
                    limit=RESULTS_PER_QUERY,
                    days_old=days_old,
                    remote_only=False,
                )
                print(f"({len(jobs)} jobs)")
                all_jobs.extend(jobs)
        
        # Also search remote-only if configured
        if INCLUDE_REMOTE:
            for source in sources:
                if source.name == "jsearch":  # JSearch has a remote filter
                    label = f"    {source.name} → \"{query}\" (Remote Brazil)"
                    print(f"{label}...", end=" ")
                    jobs = source.search(
                        query=query,
                        location="Brazil",
                        limit=RESULTS_PER_QUERY,
                        days_old=days_old,
                        remote_only=True,
                    )
                    print(f"({len(jobs)} jobs)")
                    all_jobs.extend(jobs)
    
    # Deduplicate within this career path
    unique = _deduplicate_jobs(all_jobs)
    removed = len(all_jobs) - len(unique)
    print(f"\n  Total for {path_name}: {len(all_jobs)} found → {len(unique)} unique")
    
    return unique


def search_and_match(min_score: float = 0) -> list[ScoredJob]:
    """
    🚀 MAIN FUNCTION — Full search + score pipeline.
    
    Searches across all career paths, deduplicates,
    scores with RAG, and returns ranked results.
    """
    print("=" * 60)
    print("  🔍 JOB SEARCH — Starting")
    print(f"  Recency: last {MAX_DAYS_OLD} days")
    print(f"  Locations: {', '.join(LOCATIONS)}")
    print(f"  Remote: {'Yes' if INCLUDE_REMOTE else 'No'}")
    print("=" * 60)
    
    # Get API keys from .env
    sources = get_all_sources(
        rapidapi_key=os.getenv("RAPIDAPI_KEY", ""),
    )
    
    # Search each career path
    all_jobs: list[JobPosting] = []
    job_career_path: dict[str, str] = {}  # job_id → career_path_name
    
    for career_path in CAREER_PATHS:
        jobs = search_career_path(career_path, sources, days_old=MAX_DAYS_OLD)
        for job in jobs:
            # Track which career path found this job
            if job.id not in job_career_path:
                job_career_path[job.id] = career_path["name"]
        all_jobs.extend(jobs)
    
    # Global deduplication (a job might appear in multiple career paths)
    unique_jobs = _deduplicate_jobs(all_jobs)
    print(f"\n{'=' * 60}")
    print(f"  Total unique jobs across all paths: {len(unique_jobs)}")
    
    # --- SP Metropolitan Area filter ---
    from src.jobs.config import is_sp_metro_area
    before_filter = len(unique_jobs)
    unique_jobs = [j for j in unique_jobs if is_sp_metro_area(j.location)]
    rejected = before_filter - len(unique_jobs)
    if rejected > 0:
        print(f"  Location filter: {before_filter} → {len(unique_jobs)} (removed {rejected} outside SP metro)")
    print(f"{'=' * 60}")
    
    if not unique_jobs:
        print("\nNo jobs found in SP metro area! Try adjusting location settings.")
        return []
    
    # Score each job against your career profile (RAG)
    with_desc = sum(1 for j in unique_jobs if j.description and j.description.strip())
    print(f"\n  📝 Descriptions: {with_desc}/{len(unique_jobs)} jobs have full text")
    print(f"  🧠 Scoring {len(unique_jobs)} jobs against your career...")
    scored_jobs: list[ScoredJob] = []
    
    for i, job in enumerate(unique_jobs):
        text_to_score = job.description if job.description else job.title
        result = score_job(text_to_score)
        
        # FIX FOR MISSING DESCRIPTIONS:
        # If JobSpy fails to get the description, RAG scores just the title.
        # This naturally results in a very low distance score (~20%) and the job is dropped.
        # If we have no description but the title is good, force it past the RAG filter.
        if not job.description:
            title_lw = job.title.lower()
            strong_keywords = ["product", "ops", "analyst", "analista", "dados", "business", "data", "revenue", "bi", "intelligence"]
            if any(k in title_lw for k in strong_keywords):
                result["score"] = max(result["score"], 45.0)
                result["interpretation"] = "🟠 Title Match (Missing desc)"
        
        career_path_name = job_career_path.get(job.id, "Unknown")
        
        scored = ScoredJob(
            job=job,
            score=result["score"],
            interpretation=result["interpretation"],
            top_matches=result.get("top_matches", []),
            career_path=career_path_name,
        )
        scored_jobs.append(scored)
        
        if (i + 1) % 5 == 0 or (i + 1) == len(unique_jobs):
            print(f"  Scored {i + 1}/{len(unique_jobs)}...")
    
    # Filter by minimum score
    effective_min = min_score if min_score > 0 else MIN_MATCH_SCORE
    if effective_min > 0:
        before = len(scored_jobs)
        scored_jobs = [sj for sj in scored_jobs if sj.score >= effective_min]
        print(f"  Filtered: {before} → {len(scored_jobs)} (min score: {effective_min}%)")
    
    # Sort by score (best first)
    scored_jobs.sort(key=lambda sj: sj.score, reverse=True)
    
    return scored_jobs


def print_results(scored_jobs: list[ScoredJob], show_top: int = 15):
    """Display results in a nice format."""
    if not scored_jobs:
        print("\nNo matching jobs found.")
        return
    
    print(f"\n{'=' * 70}")
    print(f"  🏆 TOP {min(show_top, len(scored_jobs))} JOB MATCHES")
    print(f"{'=' * 70}")
    
    for i, sj in enumerate(scored_jobs[:show_top]):
        print(f"\n{'─' * 70}")
        print(f"  #{i + 1} | Score: {sj.score}% {sj.interpretation}")
        print(f"  📋 Path:     {sj.career_path}")
        print(f"  💼 Title:    {sj.job.title}")
        print(f"  🏢 Company:  {sj.job.company}")
        print(f"  📍 Location: {sj.job.location}")
        print(f"  🔗 Source:   {sj.job.source}")
        if sj.job.url:
            print(f"  🌐 URL:      {sj.job.url}")
        if sj.job.posted_at:
            print(f"  📅 Posted:   {sj.job.posted_at}")


# Run the full pipeline
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    
    results = search_and_match()
    print_results(results)
    
    # Summary by career path
    if results:
        print(f"\n{'=' * 70}")
        print("  📊 SUMMARY BY CAREER PATH")
        print(f"{'=' * 70}")
        paths = {}
        for sj in results:
            paths.setdefault(sj.career_path, []).append(sj)
        for path, jobs in paths.items():
            avg_score = sum(j.score for j in jobs) / len(jobs)
            print(f"  {path}: {len(jobs)} jobs, avg score: {avg_score:.1f}%")
