"""Run Indeed searches in the visible browser, store listings, and read full job descriptions.

Descriptions are read the way a person would: click a card on the results page and read the
right-hand job pane. Pace is slow and randomised; Cloudflare checks and sign-in pages pause the
scan until the user deals with them in the window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from jobbot.browser import Notify, human_pause, wait_for_human
from jobbot.config import Search, Settings
from jobbot.db import JobStore
from jobbot.platforms.indeed import parse
from jobbot.platforms.indeed.parse import PLATFORM, SEL_CARD_LINK, SEL_DESCRIPTION
from jobbot.text import html_to_text

RESULTS_PER_PAGE_STEP = 10  # Indeed's `start` parameter step
DESCRIPTION_TIMEOUT_S = 15


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

    # ------------------------------------------------------------ public

    def run(self, searches: list[Search], max_pages: int | None = None) -> ScanStats:
        stats = ScanStats()
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
                result = self._load_results(url)
                if result is None or not result.listings:
                    break
                stats.pages += 1
                stats.logged_in = result.logged_in
                new_on_page = self._process_page(result, search, url, stats)
                stats.per_search[search.name] += new_on_page
                if len(result.listings) < RESULTS_PER_PAGE_STEP:
                    break  # last page
                human_pause(self.settings.scan.delay_min_s * 2, self.settings.scan.delay_max_s * 2)
        return stats

    # ------------------------------------------------------------ pages

    def _load_results(self, url: str) -> parse.SearchPage | None:
        self.page.goto(url, wait_until="domcontentloaded")
        self._handle_blockers()
        try:
            self.page.wait_for_selector(SEL_CARD_LINK, timeout=20000)
        except PlaywrightTimeout:
            self._handle_blockers()  # a check may have appeared late
            if self.page.locator(SEL_CARD_LINK).count() == 0:
                self.notify("  no results on this page")
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
                return text
            if attempt == 0 and self._handle_blockers():
                # We had to wait for a check/sign-in; return to the results and retry once.
                self._load_results(results_url)
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
        return waited
