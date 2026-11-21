"""Decide startup vs MNC from data before asking the LLM.

Order: user's MNC list -> company size from the platform -> (caller falls back to the LLM).
"""

from __future__ import annotations

import re
from typing import Literal

ResolvedType = Literal["startup", "mnc", "unknown"]

_SUFFIXES = re.compile(
    r"\b(private|pvt|limited|ltd|llp|llc|inc|incorporated|corp|corporation|co|company|"
    r"india|technologies|technology|solutions|services|software|global|group|plc|gmbh)\b\.?",
    re.IGNORECASE,
)


def normalize_company(name: str) -> str:
    name = name.lower().replace("&", " and ")
    name = _SUFFIXES.sub(" ", name)
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def in_mnc_list(company: str, mnc_list: list[str]) -> bool:
    norm = normalize_company(company)
    if not norm:
        return False
    for mnc in mnc_list:
        m = normalize_company(mnc)
        # Whole-word prefix match: "infosys bpm" matches "infosys"; "tcsx" does not match "tcs".
        if m and (norm == m or norm.startswith(m + " ")):
            return True
    return False


def parse_company_size(size: str | None) -> int | None:
    """Lower bound of an employee-count string: '10,000+ employees' -> 10000, '51-200' -> 51."""
    if not size:
        return None
    m = re.search(r"\d[\d,]*", size)
    return int(m.group().replace(",", "")) if m else None


def resolve_company_type(
    company: str, company_size: str | None, mnc_list: list[str], mnc_min_employees: int
) -> tuple[ResolvedType, str]:
    if in_mnc_list(company, mnc_list):
        return "mnc", "mnc_list"
    employees = parse_company_size(company_size)
    if employees is not None:
        return ("mnc" if employees >= mnc_min_employees else "startup"), "company_size"
    return "unknown", "unknown"
