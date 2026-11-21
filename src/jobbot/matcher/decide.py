"""Apply/skip decision and resume choice for one job.

Flow: rule filters -> company type from data -> LLM (schema-constrained JSON) ->
deterministic post-checks (score threshold, resume consistency) -> log.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from jobbot.config import Profile, Settings
from jobbot.llm.client import OllamaClient
from jobbot.llm.prompts import DECIDE_PROMPT_VERSION, DECIDE_SYSTEM, DECIDE_USER
from jobbot.matcher.company_type import resolve_company_type
from jobbot.matcher.filters import check_filters
from jobbot.models import Decision, Job
from jobbot.resumes.library import ResumeLibrary
from jobbot.resumes.profiler import ResumeProfile


class LLMDecision(BaseModel):
    # Field order matters: the model writes its reasoning before committing to a verdict.
    reason: str
    role_track: str
    company_type: Literal["startup", "mnc", "unknown"]
    resume_id: str
    score: int = Field(ge=0, le=100)
    decision: Literal["apply", "skip"]


def decision_schema(library: ResumeLibrary) -> dict[str, Any]:
    """LLMDecision's JSON schema with role_track / resume_id constrained to real values."""
    schema = LLMDecision.model_json_schema()
    props = schema["properties"]
    props["role_track"]["enum"] = [*library.role_tracks, "none"]
    props["resume_id"]["enum"] = [*library.ids, "none"]
    return schema


def select_resume(
    library: ResumeLibrary, role_track: str, company_type: str, llm_choice: str
) -> tuple[str | None, str | None]:
    """Pick the resume for (role_track, company_type), respecting the LLM's choice when it is
    one of the best candidates. Returns (resume_id, note-if-overridden)."""
    candidates = [r for r in library.resumes if role_track in r.roles]
    if not candidates:
        valid = library.get(llm_choice) is not None
        return (llm_choice if valid else None), None

    exact = [r for r in candidates if r.company_type == company_type]
    generic = [r for r in candidates if r.company_type == "any"]
    preferred = [r.id for r in (exact or generic or candidates)]
    if llm_choice in preferred:
        return llm_choice, None
    chosen = preferred[0]
    return chosen, (
        f"Resume changed from '{llm_choice}' to '{chosen}' "
        f"(role={role_track}, company={company_type})"
    )


def _format_resumes(library: ResumeLibrary, profiles: dict[str, ResumeProfile]) -> str:
    blocks = []
    for r in library.resumes:
        p = profiles[r.id]
        lines = [
            f"[{r.id}] tracks: {', '.join(r.roles)} | for company type: {r.company_type}",
            f"  headline: {p.headline}",
            f"  core skills: {', '.join(p.core_skills)}",
        ]
        if p.domains:
            lines.append(f"  domains: {', '.join(p.domains)}")
        if r.notes:
            lines.append(f"  note: {r.notes}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


class Matcher:
    def __init__(
        self,
        settings: Settings,
        profile: Profile,
        library: ResumeLibrary,
        profiles: dict[str, ResumeProfile],
        client: OllamaClient,
        mnc_list: list[str],
        *,
        log_path: Path | None = None,
    ) -> None:
        missing = [rid for rid in library.ids if rid not in profiles]
        if missing:
            raise ValueError(f"No profile for resumes {missing}. Run `jobbot resumes index` first.")
        self.settings = settings
        self.profile = profile
        self.library = library
        self.profiles = profiles
        self.client = client
        self.mnc_list = mnc_list
        self.log_path = log_path or settings.data_dir / "decisions.jsonl"
        self._schema = decision_schema(library)
        self._resumes_block = _format_resumes(library, profiles)
        self._tracks_block = "\n".join(f"- {k}: {v}" for k, v in library.role_tracks.items())

    def decide(self, job: Job) -> Decision:
        decision = self._decide(job)
        self._log(job, decision)
        return decision

    def _decide(self, job: Job) -> Decision:
        m = self.settings.matching
        filt = check_filters(job, self.profile, m)
        if not filt.passed:
            return Decision(
                decision="skip",
                stage="filter",
                reason=filt.reason,
                required_experience_years=filt.required_experience_years,
            )

        known_type, type_source = resolve_company_type(
            job.company, job.company_size, self.mnc_list, m.mnc_min_employees
        )
        if known_type == "unknown":
            hint = "Unknown. Infer startup or mnc from the company name and description."
        else:
            hint = f"Known: {known_type} (from {type_source}). Use this value."

        description = job.description[: self.settings.llm.max_jd_chars]
        p = self.profile
        user = DECIDE_USER.format(
            experience_years=f"{p.total_experience_years:g}",
            location=p.current_location or "not given",
            open_to_remote="yes" if p.open_to_remote else "no",
            open_to_relocate="yes" if p.open_to_relocate else "no",
            role_tracks=self._tracks_block,
            resumes=self._resumes_block,
            company_type_hint=hint,
            title=job.title or "(not given)",
            company=job.company or "(not given)",
            job_location=job.location or "(not given)",
            description=description,
            min_score=m.min_score_to_apply,
        )
        out, info = self.client.chat_json(
            system=DECIDE_SYSTEM, user=user, output_model=LLMDecision, schema=self._schema
        )

        notes: list[str] = []
        if len(job.description) > len(description):
            notes.append(f"JD truncated to {len(description)} chars for the LLM")

        company_type = known_type if known_type != "unknown" else out.company_type
        source = (
            type_source
            if known_type != "unknown"
            else ("llm" if out.company_type != "unknown" else "unknown")
        )

        final = out.decision
        if final == "apply" and out.score < m.min_score_to_apply:
            final = "skip"
            notes.append(f"LLM said apply but score {out.score} < {m.min_score_to_apply}")
        if final == "apply" and out.role_track == "none":
            final = "skip"
            notes.append("LLM said apply but role_track is 'none'")

        resume_id: str | None = None
        if final == "apply":
            resume_id, note = select_resume(
                self.library, out.role_track, company_type, out.resume_id
            )
            if note:
                notes.append(note)
            if resume_id is None:
                final = "skip"
                notes.append("No resume matches this role track")

        return Decision(
            decision=final,
            stage="llm",
            reason=out.reason,
            resume_id=resume_id,
            role_track=None if out.role_track == "none" else out.role_track,
            company_type=company_type,
            company_type_source=source,
            score=out.score,
            notes=notes,
            required_experience_years=filt.required_experience_years,
            model=info.model,
            prompt_version=DECIDE_PROMPT_VERSION,
            latency_s=info.latency_s,
        )

    def _log(self, job: Job, decision: Decision) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "job": {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "platform": job.platform,
                "description_sha256": job.description_sha256,
            },
            "decision": decision.model_dump(),
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
