"""Command-line entry point: `jobbot --help`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from jobbot.browser import BrowserError, HumanActionTimeout, open_browser, wait_for_human
from jobbot.config import (
    PROJECT_ROOT,
    ConfigError,
    Settings,
    load_mnc_list,
    load_profile,
    load_searches,
    load_settings,
    read_yaml,
)
from jobbot.db import JobStore, row_decision
from jobbot.llm.client import LLMError, OllamaClient
from jobbot.matcher.decide import Matcher
from jobbot.models import Decision, Job
from jobbot.pipeline import decide_pending
from jobbot.platforms.indeed import parse as indeed_parse
from jobbot.platforms.indeed.scanner import IndeedScanner, search_url
from jobbot.resumes.library import load_library
from jobbot.resumes.profiler import build_profiles, load_cached_profiles

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Local-LLM job matcher.")
resumes_app = typer.Typer(no_args_is_help=True, help="Manage the resume library.")
app.add_typer(resumes_app, name="resumes")
console = Console()


@app.callback()
def main(
    model: Annotated[
        str | None, typer.Option(help="Override the Ollama model for this run (e.g. llama3.2).")
    ] = None,
) -> None:
    if model:
        os.environ["JOBBOT_MODEL"] = model


def _fail(msg: str) -> None:
    console.print(f"[bold red]Error:[/] {msg}")
    raise typer.Exit(1)


# ---------------------------------------------------------------- resumes


@resumes_app.command("index")
def resumes_index(
    force: Annotated[bool, typer.Option(help="Re-profile even if cached.")] = False,
) -> None:
    """Parse every resume in resumes.yaml and cache an LLM-built profile of each."""
    try:
        settings = load_settings()
        library = load_library(settings.resumes_dir)
        with OllamaClient(settings.llm) as client:

            def progress(rid: str, status: str, latency: float | None) -> None:
                extra = f" ({latency:.1f}s)" if latency is not None else ""
                console.print(f"  {rid}: {status}{extra}")

            console.print(f"Indexing {len(library.resumes)} resumes with {settings.llm.model}...")
            profiles = build_profiles(
                library, client, settings.data_dir, force=force, on_progress=progress
            )
    except (ConfigError, LLMError) as e:
        _fail(str(e))
    _print_profiles(library, profiles)


@resumes_app.command("show")
def resumes_show() -> None:
    """Show cached resume profiles (no LLM call)."""
    try:
        settings = load_settings()
        library = load_library(settings.resumes_dir)
    except ConfigError as e:
        _fail(str(e))
    profiles = load_cached_profiles(library, settings.data_dir)
    if not profiles:
        _fail("No cached profiles. Run `jobbot resumes index` first.")
    _print_profiles(library, profiles)


def _print_profiles(library, profiles) -> None:
    for r in library.resumes:
        p = profiles.get(r.id)
        if p is None:
            console.print(f"[yellow]{r.id}: not indexed[/]")
            continue
        body = (
            f"[bold]{p.headline}[/]  ({p.seniority}, {p.total_experience_years:g} yrs)\n"
            f"tracks: {', '.join(r.roles)} | company type: {r.company_type} | file: {r.file}\n"
            f"[cyan]core:[/] {', '.join(p.core_skills)}\n"
            f"[cyan]domains:[/] {', '.join(p.domains) or '-'}\n"
            f"{p.summary}"
        )
        console.print(Panel(body, title=r.id, expand=False))


# ---------------------------------------------------------------- matching


def _build_matcher(client: OllamaClient) -> Matcher:
    settings = load_settings()
    library = load_library(settings.resumes_dir)
    profiles = build_profiles(library, client, settings.data_dir)  # no-op when cached
    return Matcher(
        settings,
        load_profile(),
        library,
        profiles,
        client,
        load_mnc_list(settings.config_dir),
    )


def _load_job_file(path: Path) -> tuple[Job, dict]:
    """A .yaml JD file holds Job fields plus an optional `expected` block; .txt is just the JD."""
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = read_yaml(path)
        expected = data.pop("expected", {}) or {}
        return Job.model_validate(data), expected
    return Job(description=path.read_text(encoding="utf-8")), {}


def _print_decision(job: Job, d: Decision) -> None:
    color = "green" if d.decision == "apply" else "red"
    lines = [
        f"[bold {color}]{d.decision.upper()}[/]"
        + (f"  with resume [bold]{d.resume_id}[/]" if d.resume_id else ""),
        f"score: {d.score if d.score is not None else '-'} | role: {d.role_track or '-'} | "
        f"company: {d.company_type} ({d.company_type_source}) | decided by: {d.stage}",
        f"reason: {d.reason}",
    ]
    if d.required_experience_years is not None:
        lines.append(f"JD asks for: {d.required_experience_years:g}+ yrs")
    lines += [f"[yellow]note:[/] {n}" for n in d.notes]
    if d.latency_s is not None:
        lines.append(f"[dim]{d.model} | {d.prompt_version} | {d.latency_s:.1f}s[/]")
    title = " @ ".join(x for x in (job.title, job.company) if x) or "job"
    console.print(Panel("\n".join(lines), title=title, expand=False))


@app.command()
def match(
    jd_file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help=".txt or .yaml")],
    title: Annotated[str | None, typer.Option(help="Job title (for .txt files)")] = None,
    company: Annotated[str | None, typer.Option(help="Company name")] = None,
    location: Annotated[str | None, typer.Option(help="Job location")] = None,
    company_size: Annotated[str | None, typer.Option(help="e.g. '10,000+ employees'")] = None,
) -> None:
    """Decide apply/skip and pick a resume for one job description."""
    job, _ = _load_job_file(jd_file)
    overrides = {
        "title": title,
        "company": company,
        "location": location,
        "company_size": company_size,
    }
    job = job.model_copy(update={k: v for k, v in overrides.items() if v is not None})
    try:
        with OllamaClient(load_settings().llm) as client:
            matcher = _build_matcher(client)
            with console.status("Asking the local model..."):
                decision = matcher.decide(job)
    except (ConfigError, LLMError, ValueError) as e:
        _fail(str(e))
    _print_decision(job, decision)


@app.command("eval")
def eval_cmd(
    jd_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)] = (
        PROJECT_ROOT / "tests" / "fixtures" / "jds"
    ),
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Print each decision")] = False,
) -> None:
    """Run the matcher on every JD .yaml in a folder and compare with `expected`."""
    files = sorted(jd_dir.glob("*.y*ml"))
    if not files:
        _fail(f"No .yaml files in {jd_dir}")

    table = Table(title=f"Matcher eval ({len(files)} JDs)")
    for col in ("JD", "expected", "got", "score", "by", "secs", "ok"):
        table.add_column(col)

    correct = 0
    latencies: list[float] = []
    try:
        with OllamaClient(load_settings().llm) as client:
            matcher = _build_matcher(client)
            for i, f in enumerate(files, 1):
                job, expected = _load_job_file(f)
                with console.status(f"[{i}/{len(files)}] {f.stem}..."):
                    d = matcher.decide(job)
                if verbose:
                    _print_decision(job, d)
                exp_dec = expected.get("decision")
                exp_res = expected.get("resume_id")
                ok = (exp_dec is None or d.decision == exp_dec) and (
                    exp_res is None or d.resume_id == exp_res
                )
                correct += ok
                if d.latency_s is not None:
                    latencies.append(d.latency_s)
                exp_str = f"{exp_dec or '?'}" + (f" / {exp_res}" if exp_res else "")
                got_str = d.decision + (f" / {d.resume_id}" if d.resume_id else "")
                table.add_row(
                    f.stem,
                    exp_str,
                    got_str,
                    "-" if d.score is None else str(d.score),
                    d.stage,
                    "-" if d.latency_s is None else f"{d.latency_s:.1f}",
                    "[green]yes[/]" if ok else "[red]NO[/]",
                )
    except (ConfigError, LLMError, ValueError) as e:
        _fail(str(e))

    console.print(table)
    avg = (
        f"{sum(latencies) / len(latencies):.1f}s avg per LLM call" if latencies else "no LLM calls"
    )
    console.print(f"[bold]{correct}/{len(files)} correct[/] | {avg}")


# ---------------------------------------------------------------- Indeed + job store

STATUS_COLORS = {
    "pending_review": "green",
    "manual": "cyan",
    "skipped": "red",
    "filtered_out": "dim",
    "duplicate": "dim",
    "failed": "yellow",
    "new": "white",
}


def _store(settings: Settings) -> JobStore:
    return JobStore(settings.data_dir / "jobs.db")


def _plain(msg: str) -> None:
    console.print(msg, markup=False, highlight=False)


@app.command()
def login(
    timeout_min: Annotated[float, typer.Option(help="Minutes to wait for you to sign in.")] = 10,
) -> None:
    """Open the bot's Chrome profile so you can sign in to Indeed once (the session is saved)."""
    settings = load_settings()
    base = settings.scan.base_url.rstrip("/")
    probe = search_url(base, load_searches(settings.config_dir)[0], 0)
    deadline_s = timeout_min * 60

    def logged_in(page) -> bool | None:
        page.goto(probe, wait_until="domcontentloaded")
        wait_for_human(
            page,
            lambda p: indeed_parse.is_challenge(p.title(), p.content()),
            ">>> Please complete the 'Verify you are human' check in the Chrome window.",
            deadline_s,
            _plain,
        )
        page.wait_for_timeout(2500)
        return indeed_parse.parse_search_page(page.content(), base).logged_in

    try:
        with open_browser(settings.browser) as (_, page):
            if logged_in(page):
                console.print("[green]Already signed in to Indeed.[/] Nothing to do.")
                return
            page.goto(f"{base}/account/login", wait_until="domcontentloaded")
            console.print(
                "[bold]Sign in to Indeed in the Chrome window that just opened.[/]\n"
                "Use your usual method (email code / Google).\n"
                "jobbot never sees your password.\n"
                f"Waiting up to {timeout_min:g} minutes..."
            )
            wait_for_human(
                page,
                lambda p: indeed_parse.is_signin(p.url) or base not in p.url,
                "Waiting for sign-in to finish...",
                deadline_s,
                _plain,
            )
            if logged_in(page):
                console.print("[green]Signed in. The session is saved in browser_profile/.[/]")
            else:
                _fail("Indeed still reports you as signed out. Run `jobbot login` again.")
    except (BrowserError, ConfigError) as e:
        _fail(str(e))


@app.command()
def scan(
    search: Annotated[
        list[str] | None, typer.Option("--search", "-s", help="Only these search names.")
    ] = None,
    pages: Annotated[int | None, typer.Option(help="Override max_pages per search.")] = None,
    decide: Annotated[bool, typer.Option(help="Run the LLM on new jobs after scanning.")] = False,
) -> None:
    """Run Indeed searches from config/searches.yaml and store new jobs with full descriptions."""
    try:
        settings = load_settings()
        searches = load_searches(settings.config_dir)
    except ConfigError as e:
        _fail(str(e))
    if search:
        unknown = set(search) - {s.name for s in searches}
        if unknown:
            _fail(f"Unknown search name(s): {', '.join(sorted(unknown))}")
        searches = [s for s in searches if s.name in search]

    with _store(settings) as store:
        stats = None
        try:
            with open_browser(settings.browser) as (_, page):
                scanner = IndeedScanner(page, store, settings, notify=_plain)
                stats = scanner.run(searches, max_pages=pages)
        except HumanActionTimeout as e:
            console.print(f"[yellow]Scan stopped:[/] {escape(str(e))} (progress is saved)")
        except BrowserError as e:
            _fail(str(e))
        except KeyboardInterrupt:
            console.print("[yellow]Scan interrupted (progress is saved).[/]")

        if stats:
            signed = {True: "yes", False: "no", None: "unknown"}[stats.logged_in]
            console.print(
                f"\n[bold]Scan done:[/] {stats.pages} pages, {stats.listings_seen} listings, "
                f"{stats.new_jobs} new jobs, {stats.descriptions} descriptions read, "
                f"{stats.description_failures} failed, {stats.duplicates} duplicates | "
                f"signed in: {signed}"
            )
            if stats.stopped_early:
                console.print(f"[yellow]Stopped early:[/] {stats.stopped_early}")
        if decide:
            _run_decide(store, settings, limit=None)


@app.command("decide")
def decide_cmd(
    limit: Annotated[int | None, typer.Option(help="Decide at most N jobs.")] = None,
    retry_failed: Annotated[bool, typer.Option(help="Retry jobs that failed before.")] = False,
) -> None:
    """Run the LLM matcher on every new job in the database."""
    settings = load_settings()
    with _store(settings) as store:
        if retry_failed:
            console.print(f"Re-queued {store.reset_failed()} failed jobs.")
        _run_decide(store, settings, limit=limit)


def _run_decide(store: JobStore, settings: Settings, *, limit: int | None) -> None:
    total = len(store.to_decide(limit))
    if total == 0:
        console.print("No new jobs to decide.")
        return
    console.print(f"Deciding {total} jobs with {settings.llm.model}...")

    def on_decision(i, n, job: Job, d: Decision | None, status_or_err: str | None) -> None:
        head = f"[{i}/{n}] {escape(job.title)} @ {escape(job.company)}"
        if d is None:
            console.print(f"{head} -> [yellow]failed[/]: {escape(status_or_err or '')}")
            return
        color = STATUS_COLORS.get(status_or_err or "", "white")
        extra = f" | {d.resume_id}" if d.resume_id else ""
        score = f" | {d.score}" if d.score is not None else ""
        console.print(f"{head} -> [{color}]{status_or_err}[/]{score}{extra}")
        console.print(f"    [dim]{escape(d.reason)}[/]")

    try:
        with OllamaClient(settings.llm) as client:
            matcher = _build_matcher(client)
            stats = decide_pending(store, matcher, limit=limit, on_decision=on_decision)
    except (ConfigError, LLMError, ValueError) as e:
        _fail(str(e))
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(stats.by_status.items())) or "nothing"
    console.print(f"[bold]Decided {stats.decided}[/] ({summary})")
    if stats.aborted:
        console.print(f"[red]Stopped - LLM unavailable:[/] {escape(stats.aborted)}")


@app.command()
def jobs(
    status: Annotated[str | None, typer.Option(help="Filter, e.g. pending_review, manual.")] = None,
    limit: Annotated[int, typer.Option(help="Max rows.")] = 30,
) -> None:
    """List jobs in the database (status counts + a table)."""
    settings = load_settings()
    with _store(settings) as store:
        counts = store.counts()
        rows = store.list_jobs(status, limit)
    if not counts:
        console.print("Database is empty. Run `jobbot scan` first.")
        return
    console.print(
        "  ".join(
            f"[{STATUS_COLORS.get(k, 'white')}]{k}[/]: {v}" for k, v in sorted(counts.items())
        )
    )
    table = Table(show_lines=False)
    for col in ("id", "status", "score", "resume", "easy", "title", "company", "location"):
        table.add_column(col, overflow="fold")
    for r in rows:
        color = STATUS_COLORS.get(r["status"], "white")
        table.add_row(
            str(r["id"]),
            f"[{color}]{r['status']}[/]",
            "" if r["score"] is None else str(r["score"]),
            r["resume_id"] or "",
            {1: "yes", 0: "no"}.get(r["easy_apply"], "?"),
            escape(r["title"]),
            escape(r["company"]),
            escape(r["location"]),
        )
    console.print(table)


@app.command()
def show(job_id: Annotated[int, typer.Argument(help="Job id from `jobbot jobs`.")]) -> None:
    """Show one job: listing data, decision and full description."""
    settings = load_settings()
    with _store(settings) as store:
        row = store.get(job_id)
    if row is None:
        _fail(f"No job with id {job_id}")
    d = row_decision(row)
    lines = [
        f"[bold]{escape(row['title'])}[/] @ {escape(row['company'])} - {escape(row['location'])}",
        f"status: {row['status']} | easy apply: {bool(row['easy_apply'])} | "
        f"salary: {escape(row['salary'] or '-')} | posted: {row['posted_at'] or '-'}",
        f"url: {row['url']}",
    ]
    if d:
        lines.append(
            f"decision: {d['decision']} | score: {d.get('score')} | resume: {d.get('resume_id')} "
            f"| company type: {d.get('company_type')} ({d.get('company_type_source')})"
        )
        lines.append(f"reason: {escape(d['reason'])}")
        lines += [f"[yellow]note:[/] {escape(n)}" for n in d.get("notes", [])]
    if row["error"]:
        lines.append(f"[yellow]error:[/] {escape(row['error'])}")
    console.print(Panel("\n".join(lines), title=f"job #{job_id}", expand=False))
    console.print(escape(row["description"] or "(no description yet)"), highlight=False)


if __name__ == "__main__":
    app()
