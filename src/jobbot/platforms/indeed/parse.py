"""Pure HTML parsing for Indeed pages (no browser here, so it is unit-testable).

All Indeed-specific selectors and markers live in this file. When Indeed changes its pages,
this is the file to fix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup

from jobbot.models import Job
from jobbot.text import html_to_text

PLATFORM = "indeed"

# Search results are embedded as JSON in the page: much more stable than the visual markup.
MOSAIC_MARKER = 'window.mosaic.providerData["mosaic-provider-jobcards"]'

# Selectors (DOM fallback + job description pane).
SEL_CARD_LINK = "a[data-jk]"
SEL_COMPANY = "[data-testid='company-name']"
SEL_LOCATION = "[data-testid='text-location']"
SEL_DESCRIPTION = "#jobDescriptionText"

CHALLENGE_TITLES = ("just a moment",)
CHALLENGE_TEXTS = ("additional verification required", "verify you are human")
SIGNIN_URL_PARTS = ("secure.indeed.com/auth", "secure.indeed.com/account/login", "/account/login")


@dataclass
class Listing:
    job: Job  # description is empty until the detail pane is read
    snippet: str | None = None
    sponsored: bool = False


@dataclass
class SearchPage:
    listings: list[Listing]
    logged_in: bool | None = None  # from Indeed's own page data, when available
    source: str = "json"  # json | dom


def parse_search_page(html: str, base_url: str) -> SearchPage:
    model = _mosaic_model(html)
    if model is not None and isinstance(model.get("results"), list):
        listings = [_from_mosaic(r, base_url) for r in model["results"] if r.get("jobkey")]
        return SearchPage(_dedupe(listings), logged_in=model.get("loggedIn"), source="json")
    return SearchPage(_dedupe(_from_dom(html, base_url)), source="dom")


def parse_description(html: str) -> str | None:
    node = BeautifulSoup(html, "html.parser").select_one(SEL_DESCRIPTION)
    if node is None:
        return None
    return html_to_text(str(node)) or None


def is_challenge(title: str, html: str) -> bool:
    t = title.lower()
    if any(c in t for c in CHALLENGE_TITLES):
        return True
    head = html[:60000].lower()
    return any(c in head for c in CHALLENGE_TEXTS)


def is_signin(url: str) -> bool:
    return any(part in url for part in SIGNIN_URL_PARTS)


# ---------------------------------------------------------------- internals


def _mosaic_model(html: str) -> dict[str, Any] | None:
    i = html.find(MOSAIC_MARKER)
    if i < 0:
        return None
    start = html.find("{", html.find("=", i + len(MOSAIC_MARKER)))
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html, start)
        return data["metaData"]["mosaicProviderJobCardsModel"]
    except (ValueError, KeyError, TypeError):
        return None


def _from_mosaic(r: dict[str, Any], base_url: str) -> Listing:
    jk = str(r["jobkey"])
    salary = (r.get("salarySnippet") or {}).get("text") or None
    pub = r.get("pubDate")
    posted = (
        datetime.fromtimestamp(pub / 1000, tz=UTC).date().isoformat()
        if isinstance(pub, int | float) and pub > 0
        else None
    )
    job = Job(
        title=r.get("displayTitle") or r.get("title") or "",
        company=r.get("company") or r.get("truncatedCompany") or "",
        location=r.get("formattedLocation") or "",
        description="",
        url=f"{base_url}/viewjob?jk={jk}",
        platform=PLATFORM,
        job_key=jk,
        easy_apply=bool(r.get("indeedApplyEnabled") or r.get("indeedApplyable")),
        remote=bool(r.get("remoteLocation")),
        salary=salary,
        posted_at=posted,
    )
    return Listing(job, html_to_text(r.get("snippet") or "") or None, bool(r.get("sponsored")))


def _from_dom(html: str, base_url: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Listing] = []
    for a in soup.select(SEL_CARD_LINK):
        jk = a.get("data-jk")
        if not jk:
            continue
        card = a.find_parent(class_="job_seen_beacon") or a.find_parent("li") or a
        company = card.select_one(SEL_COMPANY)
        location = card.select_one(SEL_LOCATION)
        card_text = card.get_text(" ", strip=True).lower()
        job = Job(
            title=a.get_text(" ", strip=True),
            company=company.get_text(" ", strip=True) if company else "",
            location=location.get_text(" ", strip=True) if location else "",
            description="",
            url=f"{base_url}/viewjob?jk={jk}",
            platform=PLATFORM,
            job_key=str(jk),
            easy_apply="easily apply" in card_text,
            remote="remote" in (location.get_text(" ", strip=True).lower() if location else ""),
        )
        out.append(Listing(job))
    return out


def _dedupe(listings: list[Listing]) -> list[Listing]:
    seen: set[str] = set()
    out = []
    for item in listings:
        if item.job.job_key not in seen:
            seen.add(item.job.job_key)
            out.append(item)
    return out
