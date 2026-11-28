"""Settings and profile loading. All YAML files are validated with pydantic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
RESUMES_DIR = PROJECT_ROOT / "resumes"
DATA_DIR = PROJECT_ROOT / "data"
PROFILE_PATH = PROJECT_ROOT / "profile.yaml"


class ConfigError(RuntimeError):
    """A config/data file is missing or invalid. The message tells the user how to fix it."""


class LLMSettings(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "gpt-oss:20b"
    temperature: float = 0.0
    num_ctx: int = 8192
    # gpt-oss takes "low" | "medium" | "high"; most other models take true/false; None = omit.
    think: str | bool | None = "low"
    timeout_s: float = 600
    max_jd_chars: int = 6000


class MatchingSettings(BaseModel):
    min_score_to_apply: int = 60
    experience_tolerance_years: float = 2.0
    senior_title_min_experience: float = 4.0
    senior_title_keywords: list[str] = Field(
        default_factory=lambda: [
            "senior",
            "sr",
            "lead",
            "principal",
            "staff",
            "architect",
            "manager",
            "head",
            "director",
            "vp",
        ]
    )
    mnc_min_employees: int = 1000
    blacklist_companies: list[str] = Field(default_factory=list)
    blacklist_keywords: list[str] = Field(default_factory=list)


class BrowserSettings(BaseModel):
    # Always headed (never headless): the user must be able to see and solve challenges.
    channel: str = "chrome"  # installed Google Chrome
    profile_dir: Path = PROJECT_ROOT / "browser_profile"
    # Seconds to wait for the user to solve a Cloudflare check / sign in before giving up.
    human_wait_timeout_s: float = 300
    # Newest failure snapshot sets (.png + .html) kept in <data_dir>/screenshots/.
    screenshots_keep: int = Field(default=50, ge=1)


class ScanSettings(BaseModel):
    base_url: str = "https://in.indeed.com"
    delay_min_s: float = 2.5  # random pause between actions (clicks, page loads)
    delay_max_s: float = 6.0
    max_new_jobs_per_run: int = 80  # stop fetching descriptions after this many new jobs


class Settings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    scan: ScanSettings = Field(default_factory=ScanSettings)
    resumes_dir: Path = RESUMES_DIR
    data_dir: Path = DATA_DIR
    config_dir: Path = CONFIG_DIR


class Search(BaseModel):
    name: str
    query: str
    location: str = "India"
    max_pages: int = 2
    fromage: int | None = 3
    sort: str = "date"
    extra_params: dict[str, str] = Field(default_factory=dict)  # raw Indeed URL params


def load_searches(config_dir: Path) -> list[Search]:
    path = config_dir / "searches.yaml"
    if not path.exists():
        raise ConfigError(f"{path} not found. Add your Indeed searches there.")
    data = read_yaml(path)
    defaults = data.get("defaults") or {}
    searches = [Search.model_validate({**defaults, **s}) for s in data.get("searches") or []]
    if not searches:
        raise ConfigError(f"No searches defined in {path}.")
    names = [s.name for s in searches]
    if len(names) != len(set(names)):
        raise ConfigError(f"Duplicate search names in {path}.")
    return searches


class Profile(BaseModel):
    """The candidate's facts. Extra keys are kept for form answers in later steps."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    total_experience_years: float
    current_location: str = ""
    preferred_locations: list[str] = Field(default_factory=list)
    open_to_remote: bool = True
    open_to_relocate: bool = True
    notice_period_days: int | None = None
    current_ctc_lpa: float | None = None
    expected_ctc_lpa: float | None = None


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e
    return data or {}


def load_settings(path: Path | None = None) -> Settings:
    path = path or CONFIG_DIR / "settings.yaml"
    settings = Settings.model_validate(read_yaml(path)) if path.exists() else Settings()
    # Relative paths in settings.yaml are relative to the project root.
    for field in ("resumes_dir", "data_dir", "config_dir"):
        value: Path = getattr(settings, field)
        if not value.is_absolute():
            setattr(settings, field, PROJECT_ROOT / value)
    if not settings.browser.profile_dir.is_absolute():
        settings.browser.profile_dir = PROJECT_ROOT / settings.browser.profile_dir
    # `jobbot --model X ...` sets this to compare models without editing settings.yaml.
    if model := os.environ.get("JOBBOT_MODEL"):
        settings.llm.model = model
    return settings


def load_profile(path: Path = PROFILE_PATH) -> Profile:
    if not path.exists():
        raise ConfigError(
            f"{path} not found. Copy profile.example.yaml to profile.yaml and fill it in."
        )
    return Profile.model_validate(read_yaml(path))


def load_mnc_list(config_dir: Path) -> list[str]:
    path = config_dir / "mnc_companies.txt"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
