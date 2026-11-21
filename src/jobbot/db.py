"""SQLite job store (data/jobs.db). One row per platform job, plus its latest decision.

Status lifecycle:
  new -> filtered_out | skipped | pending_review | manual | duplicate | failed
  pending_review -> approved | rejected -> filling -> ready_to_submit -> applied   (later steps)
`manual` = the LLM says apply, but the job is not "Easily apply" (user applies on the company site).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from jobbot.models import Decision, Job

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                 INTEGER PRIMARY KEY,
    platform           TEXT NOT NULL,
    job_key            TEXT NOT NULL,
    url                TEXT,
    title              TEXT NOT NULL DEFAULT '',
    company            TEXT NOT NULL DEFAULT '',
    location           TEXT NOT NULL DEFAULT '',
    description        TEXT,
    description_sha256 TEXT,
    snippet            TEXT,
    salary             TEXT,
    posted_at          TEXT,
    easy_apply         INTEGER,
    remote             INTEGER,
    company_size       TEXT,
    search_name        TEXT,
    status             TEXT NOT NULL DEFAULT 'new',
    decision           TEXT,
    resume_id          TEXT,
    score              INTEGER,
    reason             TEXT,
    decision_json      TEXT,
    error              TEXT,
    first_seen_at      TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    decided_at         TEXT,
    UNIQUE (platform, job_key)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_desc ON jobs (description_sha256);
"""

# Statuses a job can be in before/without an LLM decision.
UNDECIDED = ("new",)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def status_for(decision: Decision, easy_apply: bool | None) -> str:
    if decision.stage == "filter":
        return "filtered_out"
    if decision.decision == "skip":
        return "skipped"
    return "pending_review" if easy_apply else "manual"


class JobStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> JobStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ writes

    def upsert_listing(self, job: Job, *, snippet: str | None, search_name: str) -> bool:
        """Insert a job seen in search results. Returns True if it is new.

        For an existing job only listing metadata is refreshed; status and decision are kept.
        """
        if not (job.platform and job.job_key):
            raise ValueError("platform and job_key are required")
        now = _now()
        if self.get_by_key(job.platform, job.job_key) is not None:
            self.conn.execute(
                """UPDATE jobs SET easy_apply = COALESCE(?, easy_apply),
                       salary = COALESCE(?, salary), updated_at = ?
                   WHERE platform = ? AND job_key = ?""",
                (_b(job.easy_apply), job.salary, now, job.platform, job.job_key),
            )
            self.conn.commit()
            return False
        self.conn.execute(
            """INSERT INTO jobs (platform, job_key, url, title, company, location, snippet,
                   salary, posted_at, easy_apply, remote, company_size, search_name,
                   first_seen_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job.platform,
                job.job_key,
                job.url,
                job.title,
                job.company,
                job.location,
                snippet,
                job.salary,
                job.posted_at,
                _b(job.easy_apply),
                _b(job.remote),
                job.company_size,
                search_name,
                now,
                now,
            ),
        )
        self.conn.commit()
        return True

    def set_description(self, job_id: int, description: str) -> str:
        """Store the full JD. Returns the new status ('new' or 'duplicate')."""
        job = Job(description=description)
        digest = job.description_sha256
        dup = self.conn.execute(
            "SELECT id FROM jobs WHERE description_sha256 = ? AND id != ? LIMIT 1",
            (digest, job_id),
        ).fetchone()
        status = "duplicate" if dup else "new"
        error = f"Same description as job #{dup['id']}" if dup else None
        self.conn.execute(
            """UPDATE jobs SET description = ?, description_sha256 = ?, status = ?, error = ?,
                   updated_at = ? WHERE id = ?""",
            (description, digest, status, error, _now(), job_id),
        )
        self.conn.commit()
        return status

    def save_decision(self, job_id: int, decision: Decision) -> str:
        row = self.get(job_id)
        if row is None:
            raise KeyError(job_id)
        easy = None if row["easy_apply"] is None else bool(row["easy_apply"])
        status = status_for(decision, easy)
        self.conn.execute(
            """UPDATE jobs SET status = ?, decision = ?, resume_id = ?, score = ?, reason = ?,
                   decision_json = ?, error = NULL, decided_at = ?, updated_at = ?
               WHERE id = ?""",
            (
                status,
                decision.decision,
                decision.resume_id,
                decision.score,
                decision.reason,
                decision.model_dump_json(),
                _now(),
                _now(),
                job_id,
            ),
        )
        self.conn.commit()
        return status

    def mark_failed(self, job_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (error[:1000], _now(), job_id),
        )
        self.conn.commit()

    def reset_failed(self) -> int:
        """Put failed jobs back to 'new' so `jobbot decide` retries them."""
        cur = self.conn.execute(
            "UPDATE jobs SET status = 'new', error = NULL, updated_at = ? WHERE status = 'failed'",
            (_now(),),
        )
        self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------ reads

    def get(self, job_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def get_by_key(self, platform: str, job_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE platform = ? AND job_key = ?", (platform, job_key)
        ).fetchone()

    def needs_description(self, platform: str, job_key: str) -> bool:
        row = self.get_by_key(platform, job_key)
        return row is not None and row["description"] is None

    def to_decide(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = (
            "SELECT * FROM jobs WHERE status = 'new' AND description IS NOT NULL "
            "ORDER BY first_seen_at, id"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(self.conn.execute(sql))

    def list_jobs(self, status: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY score DESC, updated_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = self.conn.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        return list(rows)

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
        return {r[0]: r[1] for r in rows}


def row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        title=row["title"],
        company=row["company"],
        location=row["location"],
        description=row["description"] or "",
        company_size=row["company_size"],
        url=row["url"],
        platform=row["platform"],
        job_key=row["job_key"],
        easy_apply=None if row["easy_apply"] is None else bool(row["easy_apply"]),
        remote=None if row["remote"] is None else bool(row["remote"]),
        salary=row["salary"],
        posted_at=row["posted_at"],
    )


def row_decision(row: sqlite3.Row) -> dict[str, Any] | None:
    return json.loads(row["decision_json"]) if row["decision_json"] else None


def _b(value: bool | None) -> int | None:
    return None if value is None else int(value)
