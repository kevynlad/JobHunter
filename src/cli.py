"""
=============================================================
⌨️  CLI.PY — JobHunter Command Line Interface
=============================================================

Manage your job tracker from the terminal.

Usage:
    python -m src.cli stats           → Summary of all jobs
    python -m src.cli new             → Show unprocessed jobs
    python -m src.cli applied         → Show jobs you applied to
    python -m src.cli search "query"  → Search by title/company
    python -m src.cli mark ID STATUS  → Mark job as applied/skipped
    python -m src.cli run             → Run the full pipeline

=============================================================
"""

import sys
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.jobs.database import (
    get_stats, get_jobs_by_status, get_all_jobs,
    search_jobs, update_status, make_job_id,
)

app = typer.Typer(help="🎯 JobHunter — Job Tracker CLI")
console = Console()


def _jobs_table(jobs: list[dict], title: str = "Jobs") -> Table:
    """Create a rich table from a list of job dicts."""
    table = Table(title=title, show_lines=True)
    
    table.add_column("#", style="dim", width=3)
    table.add_column("ID", style="cyan", width=8)
    table.add_column("Title", style="bold white", max_width=40)
    table.add_column("Company", style="green", max_width=20)
    table.add_column("RAG", justify="right", style="yellow", width=5)
    table.add_column("LLM", justify="right", style="magenta", width=5)
    table.add_column("Verdict", width=6)
    table.add_column("Status", width=8)
    table.add_column("Seen", style="dim", width=10)
    
    for i, j in enumerate(jobs):
        verdict_colors = {"APPLY": "[green]APPLY[/]", "MAYBE": "[yellow]MAYBE[/]", "SKIP": "[red]SKIP[/]"}
        status_colors = {
            "NEW": "[cyan]NEW[/]",
            "APPLIED": "[green]APPLIED[/]",
            "SKIPPED": "[dim]SKIPPED[/]",
            "IGNORED": "[dim]IGNORED[/]",
        }
        
        table.add_row(
            str(i + 1),
            j.get("job_id", "")[:8],
            j.get("title", "")[:40],
            j.get("company", "")[:20],
            f"{j.get('rag_score', 0):.0f}%",
            f"{j.get('llm_score', 0)}%",
            verdict_colors.get(j.get("verdict", ""), j.get("verdict", "")),
            status_colors.get(j.get("status", ""), j.get("status", "")),
            j.get("first_seen", "")[:10],
        )
    
    return table


@app.command()
def stats():
    """📊 Show summary statistics."""
    s = get_stats()
    
    console.print(Panel.fit(
        f"[bold]📊 JobHunter Stats[/bold]\n\n"
        f"  Total vagas rastreadas: [cyan]{s['total']}[/]\n"
        f"  Novas (últimas 24h):    [green]{s['new_last_24h']}[/]\n"
        f"  RAG médio:              [yellow]{s['avg_rag']}%[/]\n"
        f"  LLM médio:              [magenta]{s['avg_llm']}%[/]\n\n"
        f"  Por status:\n" +
        "\n".join(f"    {k}: {v}" for k, v in s.get("by_status", {}).items()),
        title="🎯 JobHunter",
    ))


@app.command()
def new():
    """🆕 Show jobs with NEW status (not applied yet)."""
    jobs = get_jobs_by_status("NEW")
    if not jobs:
        console.print("[dim]No new jobs.[/]")
        return
    console.print(_jobs_table(jobs, title=f"🆕 New Jobs ({len(jobs)})"))


@app.command()
def applied():
    """✅ Show jobs you've applied to."""
    jobs = get_jobs_by_status("APPLIED")
    if not jobs:
        console.print("[dim]No applied jobs yet.[/]")
        return
    console.print(_jobs_table(jobs, title=f"✅ Applied ({len(jobs)})"))


@app.command()
def search(query: str):
    """🔍 Search jobs by title or company."""
    jobs = search_jobs(query)
    if not jobs:
        console.print(f"[dim]No jobs matching '{query}'.[/]")
        return
    console.print(_jobs_table(jobs, title=f"🔍 Search: '{query}' ({len(jobs)} results)"))


@app.command()
def mark(job_id: str, status: str):
    """✏️ Mark a job status. Status: applied, skipped, ignored, new."""
    # Allow partial job_id matches
    if len(job_id) < 16:
        # Try to find a matching job
        all_jobs = get_all_jobs(limit=500)
        matches = [j for j in all_jobs if j["job_id"].startswith(job_id)]
        if len(matches) == 0:
            console.print(f"[red]No job found with ID starting with '{job_id}'[/]")
            return
        elif len(matches) > 1:
            console.print(f"[yellow]Multiple matches for '{job_id}'. Be more specific:[/]")
            for m in matches:
                console.print(f"  {m['job_id'][:8]} — {m['title']} @ {m['company']}")
            return
        job_id = matches[0]["job_id"]
    
    success = update_status(job_id, status)
    if success:
        console.print(f"[green]✅ Job {job_id[:8]} marked as {status.upper()}[/]")
    else:
        console.print(f"[red]❌ Failed. Check job ID and status (applied/skipped/ignored/new).[/]")


@app.command()
def all(limit: int = 30):
    """📋 Show all tracked jobs."""
    jobs = get_all_jobs(limit=limit)
    if not jobs:
        console.print("[dim]No jobs in database.[/]")
        return
    console.print(_jobs_table(jobs, title=f"📋 All Jobs (showing {len(jobs)})"))


@app.command()
def run():
    """🚀 Run the full pipeline."""
    from src.pipeline import run_pipeline
    run_pipeline()


@app.command()
def detail(job_id: str):
    """🔎 Show full details of a specific job."""
    all_jobs = get_all_jobs(limit=500)
    matches = [j for j in all_jobs if j["job_id"].startswith(job_id)]
    
    if not matches:
        console.print(f"[red]No job found with ID '{job_id}'[/]")
        return
    
    j = matches[0]
    console.print(Panel.fit(
        f"[bold]{j['title']}[/bold]\n"
        f"🏢 {j['company']} ({j.get('company_tier', 'Unknown')})\n"
        f"📍 {j['location']}\n"
        f"📊 RAG: {j['rag_score']:.0f}% | LLM: {j['llm_score']}% | {j['verdict']}\n"
        f"📋 Status: {j['status']} | Nível: {j.get('seniority', 'Unknown')}\n\n"
        f"[bold]Fit:[/bold] {j.get('fit_reason', 'N/A')}\n\n"
        f"[bold]Red Flags:[/bold] {j.get('red_flags', 'None')}\n\n"
        f"🔗 {j.get('url', 'N/A')}\n"
        f"📅 Visto: {j['first_seen'][:10]} | Última vez: {j['last_seen'][:10]}",
        title=f"🔎 Job {j['job_id'][:8]}",
    ))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    app()
