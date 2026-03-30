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
from src.jobs.config import CAREER_PATHS as DEFAULT_CAREER_PATHS, LOCATIONS as DEFAULT_LOCATIONS, INCLUDE_REMOTE, MAX_DAYS_OLD, RESULTS_PER_QUERY, MIN_MATCH_SCORE, is_sp_metro_area
import logging
from src.rag.retriever import score_jobs_batch

logger = logging.getLogger(__name__)


def _get_user_search_config(user_id: int | None) -> dict:
    """
    Load per-user search config from DB.
    Falls back to config.py defaults if user has no config (or user_id is None).
    """
    if user_id is not None:
        try:
            from src.db.connection import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT search_config FROM users WHERE user_id = %s AND search_config IS NOT NULL",
                        (user_id,)
                    )
                    row = cur.fetchone()
            if row and row[0]:
                return row[0]  # psycopg2 returns JSONB as dict
        except Exception as e:
            logger.warning(f"Could not load search_config for user {user_id}: {e}. Using defaults.")

    # Fallback to hardcoded config.py
    return {
        "career_paths": DEFAULT_CAREER_PATHS,
        "locations": DEFAULT_LOCATIONS,
        "include_remote": INCLUDE_REMOTE,
        "max_days_old": MAX_DAYS_OLD,
        "results_per_query": RESULTS_PER_QUERY,
    }


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
    locations: list[str] | None = None,
    include_remote: bool = True,
    results_per_query: int = 100,
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
    _locations = locations or DEFAULT_LOCATIONS
    all_jobs: list[JobPosting] = []

    print(f"\n  Career Path: {path_name} ({len(queries)} queries)")
    print(f"  {'─' * 50}")

    for query in queries:
        for location in _locations:
            for source in sources:
                label = f"    {source.name} -> \"{query}\" in {location}"
                print(f"{label}...", end=" ")

                jobs = source.search(
                    query=query,
                    location=location,
                    limit=results_per_query,
                    days_old=days_old,
                    remote_only=False,
                )
                print(f"({len(jobs)} jobs)")
                all_jobs.extend(jobs)

        if include_remote:
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


def search_and_match(min_score: float = 0, user_id: int | None = None) -> list[ScoredJob]:
    """
    Main function: full search + score pipeline, per-user config from DB.
    """
    cfg = _get_user_search_config(user_id)
    career_paths   = cfg.get("career_paths", DEFAULT_CAREER_PATHS)
    locations      = cfg.get("locations", DEFAULT_LOCATIONS)
    include_remote = cfg.get("include_remote", INCLUDE_REMOTE)
    max_days_old   = cfg.get("max_days_old", MAX_DAYS_OLD)
    results_per_q  = cfg.get("results_per_query", RESULTS_PER_QUERY)

    print("=" * 60)
    print(f"  JOB SEARCH (user={user_id or 'default'})")
    print(f"  Locations: {', '.join(locations)}")
    print(f"  Paths: {len(career_paths)} career paths")
    print("=" * 60)

    sources = get_all_sources(
        rapidapi_key=os.getenv("RAPIDAPI_KEY", ""),
    )

    # Store per-path weight for score boosting
    path_weights: dict[str, float] = {
        cp["name"]: cp.get("weight", 1.0) for cp in career_paths
    }

    all_jobs: list[JobPosting] = []
    job_career_path: dict[str, str] = {}

    for career_path in career_paths:
        jobs = search_career_path(
            career_path, sources,
            days_old=max_days_old,
            locations=locations,
            include_remote=include_remote,
            results_per_query=results_per_q,
        )
        for job in jobs:
            if job.id not in job_career_path:
                job_career_path[job.id] = career_path["name"]
        all_jobs.extend(jobs)
    
    unique_jobs = _deduplicate_jobs(all_jobs)
    print(f"\n{'=' * 60}")
    print(f"  Total unique jobs across all paths: {len(unique_jobs)}")

    # SP metro filter
    before_filter = len(unique_jobs)
    unique_jobs = [j for j in unique_jobs if is_sp_metro_area(j.location)]
    rejected = before_filter - len(unique_jobs)
    if rejected > 0:
        print(f"  Location filter: {before_filter} -> {len(unique_jobs)} (removed {rejected} outside SP metro)")
    print(f"{'=' * 60}")
    
    if not unique_jobs:
        print("\nNo jobs found in SP metro area! Try adjusting location settings.")
        return []
    
    # --- Step 5: Score each job against your career profile (Batch RAG) ---
    with_desc = sum(1 for j in unique_jobs if j.description and j.description.strip())
    logger.info(f"📝 Descriptions: {with_desc}/{len(unique_jobs)} jobs have full text")
    logger.info(f"🧠 Scoring {len(unique_jobs)} jobs against your career (Batch Mode)...")
    
    # Prepare data for batch scoring
    jobs_to_score = []
    for job in unique_jobs:
        text_to_score = job.description if job.description and job.description.strip() else job.title
        jobs_to_score.append({"id": job.id, "text": text_to_score})
    
    # Call batch API
    try:
        batch_results = score_jobs_batch(jobs_to_score)
    except Exception as e:
        logger.error(f"❌ RAG Batch scoring failed: {e}", exc_info=True)
        batch_results = []
        
    batch_map = {res["id"]: res for res in batch_results}
    
    scored_jobs: list[ScoredJob] = []
    for job in unique_jobs:
        res = batch_map.get(job.id, {"score": 50, "interpretation": "RAG Error"})

        # Boost score based on career path weight
        career_path_name = job_career_path.get(job.id, "Unknown")
        weight = path_weights.get(career_path_name, 1.0)
        base_score = res["score"]

        # Missing description fallback
        if not job.description or not job.description.strip():
            title_lw = job.title.lower()
            strong_keywords = ["product", "ops", "analyst", "analista", "dados", "business", "data", "revenue", "bi", "intelligence", "gerente", "gestor"]
            if any(k in title_lw for k in strong_keywords):
                base_score = max(base_score, 45.0)
                res["interpretation"] = "Title Match (Missing desc)"

        final_score = min(base_score * weight, 100.0)  # cap at 100

        scored = ScoredJob(
            job=job,
            score=final_score,
            interpretation=res["interpretation"],
            top_matches=[],
            career_path=career_path_name,
        )
        scored_jobs.append(scored)
    
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
