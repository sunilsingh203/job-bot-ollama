"""Visible Chrome with a dedicated persistent profile, plus "wait for the human" helpers.

Rules (see CLAUDE.md): never headless, never script logins, never try to bypass CAPTCHAs or
Cloudflare. When a check or sign-in appears, we pause and let the user handle it in the window.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from jobbot.config import BrowserSettings

Notify = Callable[[str], None]


class BrowserError(RuntimeError):
    pass


class HumanActionTimeout(BrowserError):
    """The user did not solve a check / sign in within the timeout."""


@contextmanager
def open_browser(settings: BrowserSettings) -> Iterator[tuple[BrowserContext, Page]]:
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(settings.profile_dir),
                channel=settings.channel,
                headless=False,
                viewport={"width": 1366, "height": 900},
            )
        except PlaywrightError as e:
            raise BrowserError(
                f"Could not start Chrome ({settings.channel}) with profile "
                f"{settings.profile_dir}. Is another jobbot window still open?\n{e}"
            ) from e
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            yield ctx, page
        finally:
            try:
                ctx.close()
            except PlaywrightError:
                pass  # user already closed the window


def human_pause(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def wait_for_human(
    page: Page,
    blocked: Callable[[Page], bool],
    message: str,
    timeout_s: float,
    notify: Notify,
) -> bool:
    """If `blocked(page)`, show `message` and poll until it clears. Returns True if it waited."""
    if not _safe(blocked, page):
        return False
    notify(message)
    try:
        page.bring_to_front()
    except PlaywrightError:
        pass
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(2)
        if page.is_closed():
            raise HumanActionTimeout("The browser window was closed.")
        if not _safe(blocked, page):
            notify("Thanks - continuing.")
            time.sleep(2)
            return True
    raise HumanActionTimeout(f"Still blocked after {timeout_s:.0f}s: {message}")


def _safe(check: Callable[[Page], bool], page: Page) -> bool:
    """Run a page check, treating 'page is mid-navigation' errors as still blocked."""
    try:
        return check(page)
    except PlaywrightError:
        return True
