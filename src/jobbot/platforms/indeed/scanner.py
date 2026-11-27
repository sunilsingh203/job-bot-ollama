"""Run Indeed searches in the visible browser, store listings, and read full job descriptions.

Descriptions are read the way a person would: click a card on the results page and read the
right-hand job pane. Pace is slow and randomised; Cloudflare checks and sign-in pages pause the
scan until the user deals with them in the window.

When something unexpected happens (page load error, no cards, DOM fallback, unreadable
description, unsolved check) a failure snapshot (PNG + HTML) is saved to `data/screenshots/`.
A page-load error stops the scan; the others skip the page or job and carry on. An unsolved
check skips the item, but HUMAN_TIMEOUTS_IN_A_ROW_LIMIT of them in a row stop the scan.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlencode

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from jobbot.browser import (
    SCREENSHOTS_DIRNAME,
    HumanActionTimeout,
    Notify,
    PageLoadError,
    Snapshot,
    human_pause,
    save_snapshot,
    wait_for_human,
)
from jobbot.config import Search, Settings
from jobbot.db import JobStore
from jobbot.platforms.indeed import parse
from jobbot.platforms.indeed.parse import PLATFORM, SEL_CARD_LINK, SEL_DESCRIPTION
from jobbot.text import html_to_text

RESULTS_PER_PAGE_STEP = 10  # Indeed's `start` parameter step
DESCRIPTION_TIMEOUT_S = 15

# Failure snapshot reasons (file name slugs).
REASON_GOTO_ERROR = "goto_error"
REASON_NO_CARDS = "no_cards"
REASON_DOM_FALLBACK = "dom_fallback"
REASON_NO_DESCRIPTION = "no_description"
REASON_HUMAN_TIMEOUT = "human_timeout"
# Unsolved checks/sign-ins in a row (nothing got past a check in between) that stop the scan.
HUMAN_TIMEOUTS_IN_A_ROW_LIMIT = 2


@dataclass
class ScanStats:
    pages: int = 0
    listings_seen: int = 0
    new_jobs: int = 0
    descriptions: int = 0
    description_failures: int = 0
    duplicates: int = 0
    logged_in: bool | None = None
    per_search: dict[str, int] = field(default_factory=dict)  # search name -> new jobs
    stopped_early: str | None = None
    dom_fallback_pages: int = 0  # results pages read from the DOM (job JSON missing)
    dom_fallback_snapshot: Snapshot | None = None  # taken on the first one only
    human_timeouts: int = 0  # pages/jobs skipped after an unsolved check or sign-in


def search_url(base_url: str, search: Search, page_index: int) -> str:
    params: dict[str, str | int] = {"q": search.query, "l": search.location, "sort": search.sort}
    if search.fromage:
        params["fromage"] = search.fromage
    if page_index:
        params["start"] = page_index * RESULTS_PER_PAGE_STEP
    params.update(search.extra_params)
    return f"{base_url}/jobs?{urlencode(params)}"


class IndeedScanner:
    def __init__(self, page: Page, store: JobStore, settings: Settings, notify: Notify) -> None:
        self.page = page
        self.store = store
        self.settings = settings
        self.notify = notify
        self.base_url = settings.scan.base_url.rstrip("/")
        self.snapshot_dir = settings.data_dir / SCREENSHOTS_DIRNAME
        self._stats = ScanStats()
        self._timeouts_in_a_row = 0

    # ------------------------------------------------------------ public

    def run(self, searches: list[Search], max_pages: int | None = None) -> ScanStats:
        stats = self._stats = ScanStats()
        for search in searches:
            stats.per_search[search.name] = 0
            pages = max_pages or search.max_pages
            for page_index in range(pages):
                if self._cap_reached(stats):
                    stats.stopped_early = (
                        f"reached max_new_jobs_per_run={self.settings.scan.max_new_jobs_per_run}"
                    )
                    return stats
                url = search_url(self.base_url, search, page_index)
                self.notify(f"[{search.name}] page {page_index + 1}/{pages}")
                result = self._load_results(url, snapshot_if_empty=page_index == 0)
                if result is None or not result.listings:
                    break
                stats.pages += 1
                stats.logged_in = result.logged_in
                self._note_dom_fallback(result, stats)
                new_on_page = self._process_page(result, search, url, stats)
                stats.per_search[search.name] += new_on_page
                if len(result.listings) < RESULTS_PER_PAGE_STEP:
                    break  # last page
                human_pause(self.settings.scan.delay_min_s * 2, self.settings.scan.delay_max_s * 2)
        return stats

    # ------------------------------------------------------------ pages

    def _load_results(
        self, url: str, *, snapshot_if_empty: bool = False
    ) -> parse.SearchPage | None:
        try:
            self.page.goto(url, wait_until="domcontentloaded")
        except PlaywrightError as e:  # includes PlaywrightTimeout
            raise PageLoadError(str(e), self._snapshot(REASON_GOTO_ERROR)) from e
        if self._check_blockers("page") == "skipped":
            return None
        try:
            self.page.wait_for_selector(SEL_CARD_LINK, timeout=20000)
        except PlaywrightTimeout:
            if self._check_blockers("page") == "skipped":  # a check may have appeared late
                return None
            if self.page.locator(SEL_CARD_LINK).count() == 0:
                self.notify("  no results on this page")
                if snapshot_if_empty:
                    self._snapshot(REASON_NO_CARDS)
                return None
        human_pause(1.0, 2.5)  # let the page settle like a person would
        return parse.parse_search_page(self.page.content(), self.base_url)

    def _process_page(
        self, result: parse.SearchPage, search: Search, url: str, stats: ScanStats
    ) -> int:
        new_count = 0
        for listing in result.listings:
            stats.listings_seen += 1
            if self.store.upsert_listing(
                listing.job, snippet=listing.snippet, search_name=search.name
            ):
                new_count += 1
                stats.new_jobs += 1

        for listing in result.listings:
            jk = listing.job.job_key
            assert jk is not None
            if not self.store.needs_description(PLATFORM, jk):
                continue
            if self._cap_reached(stats):
                break
            text = self._read_description(jk, url)
            row = self.store.get_by_key(PLATFORM, jk)
            if text and row is not None:
                status = self.store.set_description(row["id"], text)
                stats.descriptions += 1
                stats.duplicates += status == "duplicate"
                self.notify(
                    f"  + {listing.job.title} @ {listing.job.company}"
                    + (" [easy apply]" if listing.job.easy_apply else "")
                    + (" (duplicate)" if status == "duplicate" else "")
                )
            else:
                stats.description_failures += 1
                self.notify(f"  ! no description: {listing.job.title} @ {listing.job.company}")
            human_pause(self.settings.scan.delay_min_s, self.settings.scan.delay_max_s)
        return new_count

    def _cap_reached(self, stats: ScanStats) -> bool:
        return stats.descriptions >= self.settings.scan.max_new_jobs_per_run

    # ------------------------------------------------------------ job pane

    def _read_description(self, jk: str, results_url: str) -> str | None:
        for attempt in range(2):
            try:
                text = self._click_and_read(jk)
            except PlaywrightError as e:
                self.notify(f"  browser error reading {jk}: {str(e).splitlines()[0]}")
                text = None
            if text:
                self._timeouts_in_a_row = 0
                return text
            if attempt == 0:
                blockers = self._check_blockers("job")
                if blockers == "skipped":
                    return None  # the human_timeout snapshot is this job's only one
                if blockers == "waited":
                    # We had to wait for a check/sign-in; return to the results and retry once.
                    if self._load_results(results_url, snapshot_if_empty=True) is None:
                        return None  # the reload already reported (and snapshotted) why
        self._snapshot(REASON_NO_DESCRIPTION, job_key=jk)
        return None

    def _click_and_read(self, jk: str) -> str | None:
        page = self.page
        already_open = f"vjk={jk}" in page.url
        before = self._pane_text()
        link = page.locator(f'{SEL_CARD_LINK}[data-jk="{jk}"]').first
        if link.count() == 0:
            return None
        if not already_open:
            link.scroll_into_view_if_needed()
            human_pause(0.4, 1.2)
            link.click()

        deadline = time.monotonic() + DESCRIPTION_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if self._blocked(page):
                return None
            if "/viewjob" in page.url:  # opened as a full page instead of the side pane
                text = parse.parse_description(page.content())
                page.go_back(wait_until="domcontentloaded")
                page.wait_for_selector(SEL_CARD_LINK, timeout=20000)
                return text
            text = self._pane_text()
            if text and (already_open or text != before) and f"vjk={jk}" in page.url:
                return text
        return None

    def _pane_text(self) -> str:
        loc = self.page.locator(SEL_DESCRIPTION)
        if loc.count() == 0:
            return ""
        return html_to_text(loc.first.inner_html())

    # ------------------------------------------------------------ blockers

    @staticmethod
    def _blocked_by_challenge(page: Page) -> bool:
        return parse.is_challenge(page.title(), page.content())

    @staticmethod
    def _blocked_by_signin(page: Page) -> bool:
        return parse.is_signin(page.url)

    def _blocked(self, page: Page) -> bool:
        return self._blocked_by_challenge(page) or self._blocked_by_signin(page)

    def _handle_blockers(self) -> bool:
        """Pause for the user if Indeed shows a check or sign-in. Returns True if it waited."""
        timeout = self.settings.browser.human_wait_timeout_s
        waited = wait_for_human(
            self.page,
            self._blocked_by_challenge,
            ">>> Indeed is showing a 'Verify you are human' check. Please complete it in the "
            "Chrome window. The scan continues automatically.",
            timeout,
            self.notify,
        )
        waited |= wait_for_human(
            self.page,
            self._blocked_by_signin,
            ">>> Indeed wants you to sign in. Please sign in in the Chrome window "
            "(one time; the session is saved).",
            timeout,
            self.notify,
        )
        self._timeouts_in_a_row = 0  # got past the checks (or there were none)
        return waited

    def _check_blockers(
        self, item: Literal["page", "job"]
    ) -> Literal["clear", "waited", "skipped"]:
        """`_handle_blockers`, but an unsolved check skips the item instead of stopping the scan.

        Re-raises `HumanActionTimeout` when the run must stop (window closed, or the guard).
        """
        try:
            waited = self._handle_blockers()
        except HumanActionTimeout as e:
            self._skip_after_human_timeout(e, item)
            return "skipped"
        return "waited" if waited else "clear"

    def _skip_after_human_timeout(self, e: HumanActionTimeout, item: str) -> None:
        snap = self._snapshot(REASON_HUMAN_TIMEOUT)
        if snap.window_closed:
            raise HumanActionTimeout(str(e), snapshot=snap) from e  # stop, as before
        self._timeouts_in_a_row += 1
        if self._timeouts_in_a_row >= HUMAN_TIMEOUTS_IN_A_ROW_LIMIT:
            raise HumanActionTimeout(
                f"{HUMAN_TIMEOUTS_IN_A_ROW_LIMIT} checks/sign-ins in a row were not solved; "
                "stopping the scan to protect the Indeed account",
                snapshot=snap,
            ) from e
        self._stats.human_timeouts += 1
        timeout = self.settings.browser.human_wait_timeout_s
        self.notify(f"  ! still blocked after {timeout:.0f}s - skipped this {item}")

    # ------------------------------------------------------------ failure snapshots

    def _snapshot(self, reason: str, job_key: str | None = None) -> Snapshot:
        return save_snapshot(
            self.page,
            self.snapshot_dir,
            reason,
            job_key=job_key,
            keep=self.settings.browser.screenshots_keep,
            notify=self.notify,
        )

    def _note_dom_fallback(self, result: parse.SearchPage, stats: ScanStats) -> None:
        if result.source != "dom":
            return
        stats.dom_fallback_pages += 1
        if stats.dom_fallback_pages == 1:
            self.notify("  job JSON missing - reading cards from the page (DOM fallback)")
            stats.dom_fallback_snapshot = self._snapshot(REASON_DOM_FALLBACK)
