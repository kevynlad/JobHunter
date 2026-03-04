"""
=============================================================
📦 MODELS.PY — Data Models for Job Postings
=============================================================

WHAT DOES THIS FILE DO?
-----------------------
This file defines the "shape" of our data using Pydantic models.

Think of it like a FORM TEMPLATE:
- A JobPosting has a title, company, location, url, etc.
- A ScoredJob is a JobPosting + a match score from our RAG

WHY USE MODELS?
--------------
Without models, a job posting would be a messy dictionary:
    job = {"titl": "Developer", "compny": "Google"}  # typos!

With models, Python validates the data automatically:
    job = JobPosting(title="Developer", company="Google")  # ✅ validated!

If you forget a required field or use the wrong type, Python
will immediately tell you — instead of crashing later.

=============================================================
"""

from datetime import datetime
from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    """
    Represents a single job posting from any source.
    
    Every job API returns data in a different format.
    We convert ALL of them into this standard format,
    so the rest of our code doesn't need to know which
    API the job came from.
    
    Fields:
        id:          Unique identifier (we generate this)
        title:       Job title, e.g. "Product Manager"
        company:     Company name, e.g. "Google"
        location:    Where the job is, e.g. "São Paulo" or "Remote"
        url:         Link to the job posting
        description: Full job description text
        salary:      Salary info if available (optional)
        source:      Which API found this job (e.g. "remotive", "arbeitnow")
        posted_at:   When the job was posted (optional)
        tags:        List of tags/skills (optional)
    """
    id: str = Field(description="Unique identifier for this job")
    title: str = Field(description="Job title")
    company: str = Field(description="Company name")
    location: str = Field(default="Not specified", description="Job location")
    url: str = Field(description="URL to the job posting")
    description: str = Field(default="", description="Full job description")
    salary: str = Field(default="", description="Salary information")
    source: str = Field(description="Which API found this job")
    posted_at: str = Field(default="", description="When the job was posted")
    tags: list[str] = Field(default_factory=list, description="Tags/skills")


class ScoredJob(BaseModel):
    """A JobPosting with match scores from RAG and LLM."""
    model_config = {"extra": "allow"}
    
    job: JobPosting
    score: float = Field(description="0-100 RAG match score")
    interpretation: str = Field(description="Human-friendly label")
    career_path: str = Field(default="", description="Which career path matched (Product/Data/CX)")
    top_matches: list[dict] = Field(
        default_factory=list,
        description="Career chunks that matched this job"
    )
    # LLM Classification fields (filled by Gemini classifier)
    llm_score: int = Field(default=0, description="0-100 LLM assessment score")
    seniority: str = Field(default="", description="Jr/Pleno/Senior/Lead/Manager")
    company_tier: str = Field(default="", description="Large/Mid/Startup/Consulting")
    fit_reason: str = Field(default="", description="Why this matches or not")
    red_flags: str = Field(default="", description="Concerns about this job")
    verdict: str = Field(default="", description="APPLY/MAYBE/SKIP")


class SearchFilters(BaseModel):
    """
    Filters for job search.
    
    When you search for jobs, you can specify:
    - What kind of job you want (query)
    - Where you want to work (location)
    - Minimum match score (min_score)
    - How many results (limit)
    """
    query: str = Field(description="Search query, e.g. 'Product Manager'")
    location: str = Field(default="", description="Location filter")
    remote_only: bool = Field(default=False, description="Only show remote jobs")
    min_score: float = Field(default=0, description="Minimum RAG match score (0-100)")
    limit: int = Field(default=20, description="Max number of results per source")
