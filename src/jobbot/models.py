"""Platform-independent data models shared across modules."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field


class Job(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    description: str
    company_size: str | None = None  # e.g. "10,000+ employees" from the platform's company page
    url: str | None = None
    platform: str | None = None
    job_key: str | None = None  # the platform's own job id (Indeed "jk")
    easy_apply: bool | None = None  # Indeed "Easily apply"
    remote: bool | None = None
    salary: str | None = None
    posted_at: str | None = None  # ISO date

    @property
    def description_sha256(self) -> str:
        return hashlib.sha256(self.description.encode("utf-8")).hexdigest()


class Decision(BaseModel):
    decision: Literal["apply", "skip"]
    stage: Literal["filter", "llm"]  # which step made the call
    reason: str
    resume_id: str | None = None
    role_track: str | None = None
    company_type: Literal["startup", "mnc", "unknown"] = "unknown"
    company_type_source: str = "unknown"  # mnc_list | company_size | llm | unknown
    score: int | None = None
    notes: list[str] = Field(default_factory=list)  # post-processing adjustments, for review
    required_experience_years: float | None = None
    model: str | None = None
    prompt_version: str | None = None
    latency_s: float | None = None
