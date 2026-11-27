"""`jobbot scan` output for stops and the summary lines (browser and scanner replaced by fakes)."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fakes import FakePage
from rich.console import Console
from typer.testing import CliRunner

from jobbot import cli
from jobbot.browser import HumanActionTimeout, PageLoadError, Snapshot
from jobbot.config import Search, Settings
from jobbot.platforms.indeed.scanner import ScanStats


@pytest.fixture
def scan_cli(tmp_path, monkeypatch):
    """Patch `jobbot.cli` so `scan` runs a scripted outcome. Returns (invoke, decide_calls)."""
    decide_calls: list[object] = []
    monkeypatch.setattr(cli, "console", Console(width=400))
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=tmp_path / "data"))
    monkeypatch.setattr(cli, "load_searches", lambda d: [Search(name="s1", query="java")])
    monkeypatch.setattr(cli, "_run_decide", lambda store, s, limit: decide_calls.append(limit))

    @contextmanager
    def fake_open_browser(settings):
        yield None, FakePage()

    monkeypatch.setattr(cli, "open_browser", fake_open_browser)

    def invoke(outcome: ScanStats | BaseException, *args: str):
        class FakeScanner:
            def __init__(self, page, store, settings, notify) -> None:
                pass

            def run(self, searches, max_pages=None) -> ScanStats:
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        monkeypatch.setattr(cli, "IndeedScanner", FakeScanner)
        return CliRunner().invoke(cli.app, ["scan", *args])

    return invoke, decide_calls


def flat(text: str) -> str:
    return " ".join(text.split())


def test_scan_page_load_error_message(scan_cli, tmp_path):
    invoke, decide_calls = scan_cli
    png = tmp_path / "data" / "screenshots" / "20261127-143005-123_goto_error.png"
    snap = Snapshot(png=png, html=png.with_suffix(".html"))
    err = PageLoadError("net::ERR_CONNECTION_REFUSED at https://x\nCall log:\n - y", snap)

    result = invoke(err, "--decide")

    assert result.exit_code == 0
    out = flat(result.output)
    assert (
        "Scan stopped: page load failed: net::ERR_CONNECTION_REFUSED at https://x. "
        f"Screenshot: {png.resolve()} (+ .html) (progress is saved)"
    ) in out
    assert "Traceback" not in result.output and "Call log" not in result.output
    assert "Scan done:" not in out
    assert decide_calls == [None]


@pytest.mark.parametrize(
    ("err", "expected"),
    [
        (
            HumanActionTimeout("The browser window was closed.", Snapshot(window_closed=True)),
            "Scan stopped: The browser window was closed. Screenshot: none (window closed) "
            "(progress is saved)",
        ),
        (
            HumanActionTimeout("Still blocked after 300s: check"),  # no snapshot attached
            "Scan stopped: Still blocked after 300s: check (progress is saved)",
        ),
    ],
)
def test_scan_window_closed_message(scan_cli, err, expected):
    invoke, decide_calls = scan_cli
    result = invoke(err, "--decide")
    assert result.exit_code == 0
    assert expected in flat(result.output)
    assert decide_calls == [None]


def test_scan_guard_stop_message(scan_cli, tmp_path):
    invoke, decide_calls = scan_cli
    png = tmp_path / "x_human_timeout.png"
    err = HumanActionTimeout(
        "2 checks/sign-ins in a row were not solved; stopping the scan to protect the Indeed "
        "account",
        Snapshot(png=png),
    )
    result = invoke(err)
    assert result.exit_code == 0
    assert (
        "Scan stopped: 2 checks/sign-ins in a row were not solved; stopping the scan to protect "
        f"the Indeed account. Screenshot: {png.resolve()} (progress is saved)"
    ) in flat(result.output)
    assert decide_calls == []  # no --decide given


def test_scan_summary_reports_dom_fallback_and_skips(scan_cli, tmp_path):
    invoke, _ = scan_cli
    png = tmp_path / "20261127-143005-123_dom_fallback.png"
    stats = ScanStats(
        pages=2,
        dom_fallback_pages=2,
        dom_fallback_snapshot=Snapshot(png=png, html=png.with_suffix(".html")),
        human_timeouts=1,
    )
    out = flat(invoke(stats).output)
    assert "Scan done: 2 pages" in out
    assert (
        f"DOM fallback used on 2 pages (job JSON missing). Screenshot: {png.resolve()} (+ .html)"
    ) in out
    assert "Skipped after an unsolved check/sign-in: 1" in out

    plain = flat(invoke(ScanStats(pages=1)).output)
    assert "DOM fallback" not in plain and "Skipped after" not in plain


def test_scan_summary_dom_fallback_without_snapshot(scan_cli):
    invoke, _ = scan_cli
    out = flat(invoke(ScanStats(pages=1, dom_fallback_pages=1)).output)
    assert "DOM fallback used on 1 pages (job JSON missing). Screenshot: not saved" in out
