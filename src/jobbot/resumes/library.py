"""The resume library: resumes/resumes.yaml describes every resume file and its labels."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from jobbot.config import ConfigError, read_yaml

CompanyType = Literal["startup", "mnc", "any"]


class ResumeEntry(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_\-]+$")
    file: str
    roles: list[str] = Field(min_length=1)
    company_type: CompanyType = "any"
    notes: str = ""


class ResumeLibrary(BaseModel):
    role_tracks: dict[str, str] = Field(min_length=1)
    resumes: list[ResumeEntry] = Field(min_length=1)
    base_dir: Path

    @property
    def ids(self) -> list[str]:
        return [r.id for r in self.resumes]

    def get(self, resume_id: str) -> ResumeEntry | None:
        return next((r for r in self.resumes if r.id == resume_id), None)

    def path_of(self, entry: ResumeEntry) -> Path:
        return self.base_dir / entry.file


def load_library(resumes_dir: Path) -> ResumeLibrary:
    path = resumes_dir / "resumes.yaml"
    if not path.exists():
        raise ConfigError(
            f"{path} not found. Copy resumes/resumes.example.yaml to resumes/resumes.yaml "
            "and list your resume files."
        )
    try:
        lib = ResumeLibrary.model_validate({**read_yaml(path), "base_dir": resumes_dir})
    except ValidationError as e:
        raise ConfigError(f"Invalid {path}:\n{e}") from e

    problems: list[str] = []
    seen: set[str] = set()
    for r in lib.resumes:
        if r.id in seen:
            problems.append(f"duplicate resume id '{r.id}'")
        seen.add(r.id)
        if not lib.path_of(r).exists():
            problems.append(f"resume '{r.id}': file not found: {lib.path_of(r)}")
        for role in r.roles:
            if role not in lib.role_tracks:
                problems.append(f"resume '{r.id}': role '{role}' is not defined in role_tracks")
    if problems:
        raise ConfigError(f"Problems in {path}:\n- " + "\n- ".join(problems))
    return lib
