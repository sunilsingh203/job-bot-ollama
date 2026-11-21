"""Cheap rule-based rejects that run before any LLM call."""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobbot.config import MatchingSettings, Profile
from jobbot.models import Job

_NUM = r"(\d{1,2}(?:\.\d+)?)"
# "3+ years", "3-5 yrs", "2 to 4 years", "5 plus years"
_EXP_RE = re.compile(
    rf"{_NUM}\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*{_NUM}\s*\+?\s*)?(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_EXP_CONTEXT_RE = re.compile(r"exp", re.IGNORECASE)
_MAX_PLAUSIBLE_YEARS = 25


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""
    required_experience_years: float | None = None


def required_experience(text: str) -> float | None:
    """Highest *minimum* years of experience the JD asks for, or None if it never says.

    Only numbers with "exp..." nearby count, so "founded 10 years ago" is ignored.
    The highest minimum is used because "3+ years Java, 1+ year AWS" really requires 3.
    """
    minimums: list[float] = []
    for m in _EXP_RE.finditer(text):
        window = text[max(0, m.start() - 50) : m.end() + 60]
        if not _EXP_CONTEXT_RE.search(window):
            continue
        low = float(m.group(1))
        if low <= _MAX_PLAUSIBLE_YEARS:
            minimums.append(low)
    return max(minimums) if minimums else None


def _contains_word(haystack: str, needle: str) -> bool:
    return re.search(rf"\b{re.escape(needle)}\b", haystack, re.IGNORECASE) is not None


def check_filters(job: Job, profile: Profile, m: MatchingSettings) -> FilterResult:
    company = job.company.lower()
    for bad in m.blacklist_companies:
        if bad.lower() and bad.lower() in company:
            return FilterResult(False, f"Blacklisted company: {bad}")

    full_text = f"{job.title}\n{job.description}"
    for kw in m.blacklist_keywords:
        if _contains_word(full_text, kw):
            return FilterResult(False, f"Blacklisted keyword: {kw}")

    years = profile.total_experience_years
    if years < m.senior_title_min_experience:
        for kw in m.senior_title_keywords:
            if _contains_word(job.title, kw):
                return FilterResult(
                    False, f"Title '{job.title}' looks senior ('{kw}') for {years} yrs experience"
                )

    required = required_experience(job.description)
    if required is not None and required > years + m.experience_tolerance_years:
        return FilterResult(
            False,
            f"Requires {required:g}+ yrs experience; you have {years:g} "
            f"(tolerance {m.experience_tolerance_years:g})",
            required,
        )
    return FilterResult(True, "", required)
