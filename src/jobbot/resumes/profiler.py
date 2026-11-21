"""Turn each resume into a compact structured profile once and cache it.

The matcher sends these short profiles to the LLM instead of full resume text, which keeps
every per-job prompt small (important when the model runs mostly on CPU).
The cache is invalidated when the file, the prompt version or the model changes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from jobbot.llm.client import OllamaClient
from jobbot.llm.prompts import (
    RESUME_PROFILE_PROMPT_VERSION,
    RESUME_PROFILE_SYSTEM,
    RESUME_PROFILE_USER,
)
from jobbot.resumes.library import ResumeLibrary
from jobbot.resumes.parser import extract_text


class ResumeProfile(BaseModel):
    headline: str
    total_experience_years: float
    seniority: Literal["intern", "entry", "mid", "senior", "lead"]
    core_skills: list[str] = Field(max_length=20)
    other_skills: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list, max_length=6)
    summary: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_path(data_dir: Path) -> Path:
    return data_dir / "resume_profiles.json"


def load_cache(data_dir: Path) -> dict[str, dict]:
    path = cache_path(data_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_profiles(
    library: ResumeLibrary,
    client: OllamaClient,
    data_dir: Path,
    *,
    force: bool = False,
    on_progress=None,
) -> dict[str, ResumeProfile]:
    """Return a profile for every resume, calling the LLM only for new/changed ones."""
    cache = load_cache(data_dir)
    model = client.settings.model
    profiles: dict[str, ResumeProfile] = {}
    changed = False

    for entry in library.resumes:
        path = library.path_of(entry)
        digest = _sha256(path)
        cached = cache.get(entry.id)
        fresh = (
            cached
            and cached.get("sha256") == digest
            and cached.get("prompt_version") == RESUME_PROFILE_PROMPT_VERSION
            and cached.get("model") == model
        )
        if fresh and not force:
            profiles[entry.id] = ResumeProfile.model_validate(cached["profile"])
            if on_progress:
                on_progress(entry.id, "cached", None)
            continue

        if on_progress:
            on_progress(entry.id, "profiling", None)
        text = extract_text(path)
        profile, info = client.chat_json(
            system=RESUME_PROFILE_SYSTEM,
            user=RESUME_PROFILE_USER.format(resume_text=text),
            output_model=ResumeProfile,
        )
        profiles[entry.id] = profile
        cache[entry.id] = {
            "sha256": digest,
            "file": entry.file,
            "prompt_version": RESUME_PROFILE_PROMPT_VERSION,
            "model": model,
            "profile": profile.model_dump(),
        }
        changed = True
        if on_progress:
            on_progress(entry.id, "done", info.latency_s)

    # Drop cache entries for resumes removed from resumes.yaml.
    for stale in set(cache) - set(library.ids):
        del cache[stale]
        changed = True

    if changed:
        data_dir.mkdir(parents=True, exist_ok=True)
        cache_path(data_dir).write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return profiles


def load_cached_profiles(library: ResumeLibrary, data_dir: Path) -> dict[str, ResumeProfile]:
    """Profiles from cache only (no LLM). Missing resumes are simply absent."""
    cache = load_cache(data_dir)
    return {
        rid: ResumeProfile.model_validate(cache[rid]["profile"])
        for rid in library.ids
        if rid in cache
    }
