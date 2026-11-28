"""Minimal fake Playwright page for scanner and snapshot tests (no browser, no network).

Only the calls the scanner and the snapshot helper make are implemented. Every call is logged in
`page.calls` as `(method, arg)` so tests can check what the code did to the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from jobbot.platforms.indeed.parse import MOSAIC_MARKER, SEL_CARD_LINK, SEL_DESCRIPTION

CHALLENGE_HTML = "<html><body><h1>Additional Verification Required</h1></body></html>"
EMPTY_HTML = "<html><body><p>No jobs found.</p></body></html>"


def results_html(
    job_keys: list[str], *, json_data: bool = True, json_keys: list[str] | None = None
) -> str:
    """A results page with `a[data-jk]` cards, plus the job-cards JSON unless `json_data=False`.

    `json_keys` sets the jobs listed in the JSON (default: the same as the cards).
    """
    cards = "".join(f'<li><a data-jk="{jk}">Developer {jk}</a></li>' for jk in job_keys)
    script = ""
    if json_data:
        model = {
            "results": [
                {"jobkey": jk, "displayTitle": f"Developer {jk}", "company": "Acme"}
                for jk in (job_keys if json_keys is None else json_keys)
            ],
            "loggedIn": True,
        }
        payload = json.dumps({"metaData": {"mosaicProviderJobCardsModel": model}})
        script = f"<script>{MOSAIC_MARKER}={payload};</script>"
    return f"<html><head>{script}</head><body><ul>{cards}</ul></body></html>"


class FakeLocator:
    def __init__(self, page: FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> FakeLocator:
        return self

    def _job_key(self) -> str | None:
        m = re.search(r'\[data-jk="([^"]*)"\]', self.selector)
        return m.group(1) if m else None

    def count(self) -> int:
        page = self.page
        if self.selector == SEL_DESCRIPTION:
            return 1 if page.pane else 0
        jk = self._job_key()
        if jk is not None:
            on_page = f'data-jk="{jk}"' in page.html and jk not in page.missing_cards
            return 1 if on_page else 0
        if self.selector == SEL_CARD_LINK:
            return page.html.count("data-jk=")
        raise AssertionError(f"unexpected selector {self.selector}")

    def scroll_into_view_if_needed(self) -> None:
        self.page.calls.append(("scroll_into_view_if_needed", self.selector))

    def click(self) -> None:
        page = self.page
        jk = self._job_key()
        page.calls.append(("click", jk or self.selector))
        assert jk is not None
        page.url = f"{page.results_url}&vjk={jk}"
        page.challenge = jk in page.challenge_jobs
        page._polls = 0
        page.pane = page.descriptions.get(jk, "")

    def inner_html(self) -> str:
        return f"<div><p>{self.page.pane}</p></div>"


class FakePage:
    """A scripted results page.

    - `pages`: URL -> HTML, or a list of HTML consumed one `goto` at a time (the last repeats).
      Unknown URLs give an empty page (no cards).
    - `goto_errors`: URLs whose `goto` raises a Playwright error.
    - `challenge_urls`: URLs that show a Cloudflare check after `goto`.
    - `challenge_jobs`: job keys whose card click brings up a check.
    - `clear_after_polls` / `close_after_polls`: a showing check clears (or the window closes)
      after this many `is_closed` polls by `wait_for_human`.
    - `descriptions`: job key -> pane text. Missing keys leave the pane empty.
    - `missing_cards`: job keys whose card can't be found on the page.
    - `screenshot_error` / `content_error`: make `screenshot` / `content` raise.
    - `fail_snapshot`: `screenshot` raises, and so does a `content` call right after it (only the
      snapshot does that), so the scan itself still reads the page.
    """

    def __init__(
        self,
        pages: dict[str, str | list[str]] | None = None,
        *,
        goto_errors: set[str] | None = None,
        challenge_urls: set[str] | None = None,
        challenge_jobs: set[str] | None = None,
        clear_after_polls: int | None = None,
        close_after_polls: int | None = None,
        descriptions: dict[str, str] | None = None,
        missing_cards: set[str] | None = None,
        screenshot_error: bool = False,
        content_error: bool = False,
        fail_snapshot: bool = False,
    ) -> None:
        self.pages = {k: list(v) if isinstance(v, list) else [v] for k, v in (pages or {}).items()}
        self.goto_errors = goto_errors or set()
        self.challenge_urls = challenge_urls or set()
        self.challenge_jobs = challenge_jobs or set()
        self.clear_after_polls = clear_after_polls
        self.close_after_polls = close_after_polls
        self.descriptions = descriptions or {}
        self.missing_cards = missing_cards or set()
        self.screenshot_error = screenshot_error
        self.content_error = content_error
        self.fail_snapshot = fail_snapshot

        self.calls: list[tuple[str, object]] = []
        self.url = "about:blank"
        self.results_url = "about:blank"
        self.html = EMPTY_HTML
        self.pane = ""
        self.challenge = False
        self.closed = False
        self._polls = 0

    # -------------------------------------------------- navigation

    def goto(self, url: str, wait_until: str = "load") -> None:
        self.calls.append(("goto", url))
        if url in self.goto_errors:
            raise PlaywrightError(f"net::ERR_CONNECTION_REFUSED at {url}\nCall log:\n  - x")
        queue = self.pages.get(url)
        if queue:
            self.html = queue.pop(0) if len(queue) > 1 else queue[0]
        else:
            self.html = EMPTY_HTML
        self.url = self.results_url = url
        self.pane = ""
        self.challenge = url in self.challenge_urls
        self._polls = 0

    def wait_for_selector(self, selector: str, timeout: float = 30000) -> None:
        self.calls.append(("wait_for_selector", selector))
        if self.challenge or "data-jk=" not in self.html:
            raise PlaywrightTimeout(f"Timeout {timeout:.0f}ms exceeded.")

    def go_back(self, wait_until: str = "load") -> None:
        self.calls.append(("go_back", None))

    def bring_to_front(self) -> None:
        self.calls.append(("bring_to_front", None))

    # -------------------------------------------------- reading

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def title(self) -> str:
        return "Just a moment..." if self.challenge else "Jobs | Indeed"

    def content(self) -> str:
        last = self.calls[-1][0] if self.calls else None
        self.calls.append(("content", None))
        if self.content_error or (self.fail_snapshot and last == "screenshot"):
            raise PlaywrightError("Target crashed\nmore detail")
        return CHALLENGE_HTML if self.challenge else self.html

    def screenshot(self, path: str, full_page: bool = False, timeout: float = 30000) -> bytes:
        self.calls.append(("screenshot", path))
        if self.screenshot_error or self.fail_snapshot:
            raise PlaywrightError("Timeout 10000ms exceeded.\nCall log: ...")
        Path(path).write_bytes(b"PNG")
        return b"PNG"

    def is_closed(self) -> bool:
        self.calls.append(("is_closed", None))
        if self.challenge:
            self._polls += 1
            if self.close_after_polls is not None and self._polls >= self.close_after_polls:
                self.closed = True
            elif self.clear_after_polls is not None and self._polls >= self.clear_after_polls:
                self.challenge = False
        return self.closed

    # -------------------------------------------------- helpers for tests

    def methods(self) -> list[str]:
        return [name for name, _ in self.calls]
