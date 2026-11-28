"""Visible Chrome with a dedicated persistent profile, plus "wait for the human" helpers.

Rules (see CLAUDE.md): never headless, never script logins, never try to bypass CAPTCHAs or
Cloudflare. When a check or sign-in appears, we pause and let the user handle it in the window.

Also holds the failure-snapshot helper (`save_snapshot`): a local PNG + HTML of the current page,
written to `<data_dir>/screenshots/` when something on the site doesn't look as expected. It only
reads the page (never navigates or clicks) and never raises.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from jobbot.config import PROJECT_ROOT, BrowserSettings

Notify = Callable[[str], None]

SCREENSHOTS_DIRNAME = "screenshots"
SNAPSHOT_TIMEOUT_MS = 10_000  # a hung page can't stall the scan for Playwright's default 30 s
MAX_KEY_CHARS = 32
_REASON_RE = re.compile(r"[a-z][a-z_]*")
_STEM_RE = re.compile(r"\d{8}-\d{6}-\d{3}_[a-z][a-z_]*(?:_[A-Za-z0-9]{1,32})?")
_SNAPSHOT_SUFFIXES = (".png", ".html")


@dataclass(frozen=True)
class Snapshot:
    """What a failure snapshot managed to write."""

    png: Path | None = None
    html: Path | None = None
    window_closed: bool = False

    @property
    def saved(self) -> bool:
        return self.png is not None or self.html is not None

    def describe(self) -> str:
        if self.window_closed:
            return "none (window closed)"
        if self.png is not None and self.html is not None:
            return f"{display_path(self.png)} (+ .html)"
        if self.png is not None:
            return display_path(self.png)
        if self.html is not None:
            return display_path(self.html)
        return "not saved"


class BrowserError(RuntimeError):
    pass


class HumanActionTimeout(BrowserError):
    """The user did not solve a check / sign in within the timeout."""

    def __init__(self, message: str, snapshot: Snapshot | None = None) -> None:
        super().__init__(message)
        self.snapshot = snapshot


class PageLoadError(BrowserError):
    """A results page failed to load (network error, timeout, Chrome error page). Stops the scan."""

    def __init__(self, detail: str, snapshot: Snapshot | None = None) -> None:
        super().__init__(f"page load failed: {_first_line(detail)}")
        self.snapshot = snapshot


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


# ---------------------------------------------------------------- failure snapshots


def _first_line(error: object) -> str:
    """First non-empty line of an error message (never page content or a whole call log)."""
    lines = str(error).strip().splitlines()
    if lines:
        return lines[0]
    return type(error).__name__ if isinstance(error, BaseException) else ""


def sanitize_job_key(job_key: str | None) -> str:
    """Keep only [A-Za-z0-9] of a scraped job key, cut to MAX_KEY_CHARS. "" if nothing is left."""
    return re.sub(r"[^A-Za-z0-9]", "", job_key or "")[:MAX_KEY_CHARS]


def snapshot_stem(when: datetime, reason: str, job_key: str | None = None) -> str:
    """`<YYYYMMDD-HHMMSS-mmm>_<reason>[_<key>]`. `reason` must be a code constant slug."""
    if not _REASON_RE.fullmatch(reason):
        raise ValueError(f"invalid snapshot reason: {reason!r}")
    stamp = f"{when:%Y%m%d-%H%M%S}-{when.microsecond // 1000:03d}"
    key = sanitize_job_key(job_key)
    return f"{stamp}_{reason}_{key}" if key else f"{stamp}_{reason}"


def snapshots_to_prune(names: Iterable[str], keep: int) -> list[str]:
    """File names of every snapshot set after the newest `keep`. Other names are ignored."""
    sets: dict[str, list[str]] = {}
    for name in names:
        path = Path(name)
        if path.suffix in _SNAPSHOT_SUFFIXES and _STEM_RE.fullmatch(path.stem):
            sets.setdefault(path.stem, []).append(name)
    # The fixed-width timestamp prefix sorts lexically in time order.
    stems = sorted(sets, reverse=True)
    return sorted(name for stem in stems[max(keep, 0) :] for name in sets[stem])


def prune_snapshots(directory: Path, keep: int, notify: Notify) -> None:
    """Delete snapshot sets beyond the newest `keep` in `directory`. Never raises."""
    try:
        names = [p.name for p in directory.iterdir() if p.is_file()]
    except Exception as e:
        notify(f"  ! could not list old screenshots: {_first_line(e)}")
        return
    for name in snapshots_to_prune(names, keep):
        try:
            (directory / name).unlink()
        except Exception as e:
            notify(f"  ! could not delete old screenshot {name}: {_first_line(e)}")


def display_path(path: Path) -> str:
    """Relative to the project root when inside it, else absolute."""
    try:
        resolved = path.resolve()
    except Exception:
        return str(path)
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def save_snapshot(
    page: Page,
    directory: Path,
    reason: str,
    *,
    keep: int,
    notify: Notify,
    job_key: str | None = None,
    now: Callable[[], datetime] = datetime.now,
) -> Snapshot:
    """Save a screenshot + the HTML of the current page. Read-only; never raises.

    Only `page.is_closed`, `page.screenshot` and `page.content` are called: no navigation,
    clicks, typing or waiting. Errors become one warning line through `notify`.
    """
    try:
        closed = page.is_closed()
    except Exception:
        closed = False
    if closed:
        notify("  no screenshot (window closed)")
        return Snapshot(window_closed=True)

    try:
        stem = snapshot_stem(now(), reason, job_key)
        directory.mkdir(parents=True, exist_ok=True)
        base = directory.resolve()
        if (base / stem).resolve().parent != base:  # defence in depth: stay inside the folder
            raise ValueError(f"snapshot name {stem!r} leaves {directory}")
    except Exception as e:
        notify(f"  ! could not save screenshot: {_first_line(e)}")
        return Snapshot()

    png_path = directory / f"{stem}.png"
    html_path = directory / f"{stem}.html"
    png: Path | None = None
    html: Path | None = None
    errors: list[str] = []
    try:
        page.screenshot(path=str(png_path), full_page=True, timeout=SNAPSHOT_TIMEOUT_MS)
        png = png_path
    except Exception as e:
        errors.append(f"png: {_first_line(e)}")
    try:
        html_path.write_text(page.content(), encoding="utf-8")
        html = html_path
    except Exception as e:
        errors.append(f"html: {_first_line(e)}")
    if errors:
        notify(f"  ! could not save screenshot: {'; '.join(errors)}")

    snap = Snapshot(png=png, html=html)
    if snap.saved:
        notify(f"  screenshot: {snap.describe()}")
        prune_snapshots(directory, keep, notify)
    return snap
