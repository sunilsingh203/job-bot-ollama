"""IndeedScanner failure handling with a fake page (no browser, no Indeed, no network)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes import FakePage, results_html

from jobbot.browser import HumanActionTimeout, PageLoadError
from jobbot.config import BrowserSettings, ScanSettings, Search, Settings
from jobbot.db import JobStore
from jobbot.platforms.indeed import scanner as scanner_mod
from jobbot.platforms.indeed.scanner import IndeedScanner, ScanStats, search_url

BASE = "https://in.indeed.com"


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    monkeypatch.setattr(scanner_mod, "human_pause", lambda a, b: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(scanner_mod, "DESCRIPTION_TIMEOUT_S", 2)


class Run:
    """One scanner + store + collected notify messages, in its own folder."""

    def __init__(self, root: Path, page: FakePage, *, wait_s: float = 0.0) -> None:
        self.root = root
        self.page = page
        self.store = JobStore(root / "jobs.db")
        self.messages: list[str] = []
        settings = Settings(
            data_dir=root / "data",
            browser=BrowserSettings(human_wait_timeout_s=wait_s, profile_dir=root / "bp"),
            scan=ScanSettings(base_url=BASE),
        )
        self.scanner = IndeedScanner(page, self.store, settings, notify=self.messages.append)

    @property
    def shot_dir(self) -> Path:
        return self.root / "data" / "screenshots"

    def snaps(self) -> list[str]:
        """Snapshot sets on disk, as `<reason>[_<key>]` (the timestamp prefix dropped)."""
        if not self.shot_dir.exists():
            return []
        return sorted({p.stem.split("_", 1)[1] for p in self.shot_dir.iterdir()})

    def gotos(self) -> list[object]:
        return [arg for name, arg in self.page.calls if name == "goto"]

    def description(self, jk: str) -> str | None:
        row = self.store.get_by_key("indeed", jk)
        assert row is not None
        return row["description"]

    def lines(self, text: str) -> list[str]:
        return [m for m in self.messages if text in m]


@pytest.fixture
def make_run(tmp_path) -> Iterator:
    runs: list[Run] = []

    def make(page: FakePage, *, wait_s: float = 0.0, sub: str = "run") -> Run:
        run = Run(tmp_path / sub, page, wait_s=wait_s)
        runs.append(run)
        return run

    yield make
    for run in runs:
        run.store.close()


def search(name: str, pages: int = 2) -> Search:
    return Search(name=name, query=name, max_pages=pages)


def url(s: Search, page_index: int = 0) -> str:
    return search_url(BASE, s, page_index)


def keys(prefix: str, n: int) -> list[str]:
    return [f"{prefix}{i}" for i in range(n)]


def descs(job_keys: list[str]) -> dict[str, str]:
    return {jk: f"Description for {jk}" for jk in job_keys}


S1, S2, S3 = search("s1"), search("s2"), search("s3")


# ------------------------------------------------------------------ regression


def test_json_scan_takes_no_snapshot(make_run):
    ks = keys("a", 3)
    run = make_run(FakePage({url(S1): results_html(ks)}, descriptions=descs(ks)))
    stats = run.scanner.run([S1])
    assert (stats.pages, stats.new_jobs, stats.descriptions) == (1, 3, 3)
    assert stats.dom_fallback_pages == 0 and stats.human_timeouts == 0
    assert not run.shot_dir.exists()


# ------------------------------------------------------------------ F-1 goto error (AC-C6)


@pytest.mark.parametrize("when", ["first", "later"])
def test_goto_error_stops_scan_with_snapshot(make_run, when):
    ks = keys("a", 3)
    failing = url(S1) if when == "first" else url(S2)
    page = FakePage({url(S1): results_html(ks)}, descriptions=descs(ks), goto_errors={failing})
    run = make_run(page)

    with pytest.raises(PageLoadError) as info:
        run.scanner.run([S1, S2, S3])

    err = info.value
    assert str(err).startswith("page load failed: net::ERR_CONNECTION_REFUSED")
    assert "Call log" not in str(err)
    assert err.snapshot is not None and err.snapshot.saved
    assert run.snaps() == ["goto_error"]
    calls = page.methods()
    last_goto = len(calls) - 1 - calls[::-1].index("goto")
    assert page.calls[last_goto] == ("goto", failing)
    assert set(calls[last_goto + 1 :]) <= {"is_closed", "screenshot", "content"}  # snapshot only
    if when == "later":
        assert run.gotos() == [url(S1), url(S2)]
        assert all(run.description(jk) == f"Description for {jk}" for jk in ks)  # kept
    else:
        assert run.gotos() == [url(S1)]


def test_goto_error_without_snapshot_still_stops(make_run):
    page = FakePage(goto_errors={url(S1)}, screenshot_error=True, content_error=True)
    run = make_run(page)
    with pytest.raises(PageLoadError) as info:
        run.scanner.run([S1, S2])
    assert info.value.snapshot is not None
    assert info.value.snapshot.describe() == "not saved"
    assert len(run.lines("! could not save screenshot")) == 1
    assert run.gotos() == [url(S1)]


# ------------------------------------------------------------------ F-2 no cards (AC-C8)


def test_no_cards_on_first_page_snapshots_and_continues(make_run):
    ks = keys("b", 3)
    run = make_run(FakePage({url(S2): results_html(ks)}, descriptions=descs(ks)))
    stats = run.scanner.run([S1, S2])
    assert run.lines("no results on this page")
    assert run.snaps() == ["no_cards"]
    assert run.gotos() == [url(S1), url(S2)]  # paging for s1 stopped, s2 still loaded
    assert stats.new_jobs == 3


def test_no_cards_after_full_page_is_end_of_results(make_run):
    ks = keys("c", 10)
    run = make_run(FakePage({url(S1, 0): results_html(ks)}, descriptions=descs(ks)))
    stats = run.scanner.run([S1])
    assert run.gotos() == [url(S1, 0), url(S1, 1)]
    assert run.lines("no results on this page")
    assert run.snaps() == []
    assert stats.pages == 1 and stats.descriptions == 10


def test_no_cards_on_retry_reload_snapshots_once(make_run):
    # The check clears while reading k0, then the results reload shows no cards.
    page = FakePage(
        {url(S1): [results_html(["k0"]), "<html><body>empty</body></html>"]},
        challenge_jobs={"k0"},
        clear_after_polls=1,
        descriptions=descs(["k0"]),
    )
    run = make_run(page, wait_s=5)
    stats = run.scanner.run([S1])
    assert run.lines("Thanks - continuing.")
    assert run.gotos() == [url(S1), url(S1)]
    assert run.snaps() == ["no_cards"]  # no extra no_description set
    assert run.description("k0") is None
    assert stats.description_failures == 1 and stats.human_timeouts == 0
    assert run.lines("! no description")


# ------------------------------------------------------------------ F-3 DOM fallback (AC-C9)


def test_dom_fallback_snapshot_once_per_run(make_run):
    first, second = keys("d", 10), keys("e", 3)
    page = FakePage(
        {
            url(S1, 0): results_html(first, json_data=False),
            url(S1, 1): results_html(second, json_data=False),
        },
        descriptions=descs(first + second),
    )
    run = make_run(page)
    stats = run.scanner.run([S1])
    assert stats.dom_fallback_pages == 2
    assert stats.dom_fallback_snapshot is not None and stats.dom_fallback_snapshot.saved
    assert run.snaps() == ["dom_fallback"]
    assert len(run.lines("DOM fallback")) == 1
    assert stats.new_jobs == 13 and stats.descriptions == 13  # processed as before


# ------------------------------------------------- empty job JSON with cards (review F-1)


def test_json_empty_on_first_page_snapshots_and_skips_search(make_run):
    # Cards are on the page, but the job JSON lists none: warn, snapshot, never read the cards.
    page = FakePage(
        {
            url(S1): results_html(["r0", "r1"], json_keys=[]),
            url(S2): results_html(["k0"]),
        },
        descriptions=descs(["k0"]),
    )
    run = make_run(page)
    stats = run.scanner.run([S1, S2])
    assert run.snaps() == ["json_empty"]
    assert len(run.lines("job JSON lists no jobs")) == 1
    for jk in ("r0", "r1"):  # the cards are never stored as jobs
        assert run.store.get_by_key("indeed", jk) is None
    assert stats.new_jobs == 1 and stats.per_search == {"s1": 0, "s2": 1}  # next search ran


def test_json_empty_after_full_page_is_end_of_results(make_run):
    first = keys("f", 10)
    page = FakePage(
        {
            url(S1, 0): results_html(first),
            url(S1, 1): results_html(["r0"], json_keys=[]),  # e.g. "jobs you may like" cards
        },
        descriptions=descs(first),
    )
    run = make_run(page)
    stats = run.scanner.run([S1])
    assert run.snaps() == []
    assert run.lines("job JSON lists no jobs") == []
    assert stats.new_jobs == 10


# ------------------------------------------------------------------ F-4 no description (AC-C10)


def test_unreadable_description_snapshots_once_and_moves_on(make_run):
    page = FakePage(
        {url(S1): results_html(["k0", "k1"])}, descriptions=descs(["k1"]), missing_cards={"k0"}
    )
    run = make_run(page)
    stats = run.scanner.run([S1])
    assert run.snaps() == ["no_description_k0"]
    assert run.description("k0") is None
    assert run.description("k1") == "Description for k1"
    assert (stats.description_failures, stats.descriptions) == (1, 1)
    assert ("click", "k1") in page.calls


# ------------------------------------------------------------------ AC-C12


def _scenario(kind: str, *, fail_snapshot: bool) -> tuple[FakePage, list[Search]]:
    if kind == "no_cards":
        ks = keys("b", 3)
        page = FakePage(
            {url(S2): results_html(ks)}, descriptions=descs(ks), fail_snapshot=fail_snapshot
        )
        return page, [S1, S2]
    page = FakePage(
        {url(S1): results_html(["k0", "k1"])},
        descriptions=descs(["k1"]),
        missing_cards={"k0"},
        fail_snapshot=fail_snapshot,
    )
    return page, [S1]


def _outcome(run: Run, stats: ScanStats) -> tuple:
    rows = run.store.conn.execute("SELECT job_key, description FROM jobs ORDER BY job_key")
    counters = (stats.pages, stats.listings_seen, stats.new_jobs, stats.descriptions)
    return [tuple(r) for r in rows], counters, stats.description_failures, run.gotos()


@pytest.mark.parametrize("kind", ["no_cards", "no_description"])
def test_failed_snapshot_keeps_scan_path(make_run, kind):
    ok_page, searches = _scenario(kind, fail_snapshot=False)
    ok = make_run(ok_page, sub="ok")
    ok_stats = ok.scanner.run(searches)

    bad_page, searches = _scenario(kind, fail_snapshot=True)
    bad = make_run(bad_page, sub="bad")
    bad_stats = bad.scanner.run(searches)

    assert ok.snaps() and not bad.snaps()
    assert _outcome(bad, bad_stats) == _outcome(ok, ok_stats)
    assert len(bad.lines("! could not save screenshot")) == 1
    assert not ok.lines("! could not save screenshot")


# ------------------------------------------------------------------ F-5 human timeout (AC-C11)


def test_human_timeout_on_results_page_skips_page(make_run):
    ks = keys("b", 3)
    page = FakePage({url(S2): results_html(ks)}, descriptions=descs(ks), challenge_urls={url(S1)})
    run = make_run(page)

    stats = run.scanner.run([S1, S2])  # returns normally

    assert run.snaps() == ["human_timeout"]
    assert stats.human_timeouts == 1 and stats.new_jobs == 3
    assert run.lines("! still blocked after 0s - skipped this page")
    assert run.gotos() == [url(S1), url(S2)]  # s1 page 2 not loaded (A-8)
    # While blocked the bot only looked at the page: no clicks, no typing, no navigation.
    calls = page.methods()
    blocked_part = calls[1 : calls.index("goto", 1)]
    assert set(blocked_part) <= {"title", "content", "is_closed", "bring_to_front", "screenshot"}


def test_human_timeout_in_description_skips_job(make_run):
    page = FakePage(
        {url(S1): results_html(["k0", "k1"])},
        descriptions=descs(["k0", "k1"]),
        challenge_jobs={"k0"},
    )
    run = make_run(page)
    stats = run.scanner.run([S1])
    assert run.snaps() == ["human_timeout"]  # no extra no_description set
    assert run.lines("! still blocked after 0s - skipped this job")
    assert run.lines("! no description")
    assert run.description("k0") is None
    assert run.description("k1") == "Description for k1"
    assert (stats.human_timeouts, stats.description_failures, stats.descriptions) == (1, 1, 1)


def test_human_timeout_window_closed_stops_scan(make_run):
    page = FakePage(challenge_urls={url(S1)}, close_after_polls=1)
    run = make_run(page, wait_s=5)
    with pytest.raises(HumanActionTimeout) as info:
        run.scanner.run([S1, S2])
    assert str(info.value) == "The browser window was closed."
    assert info.value.snapshot is not None and info.value.snapshot.window_closed
    assert "screenshot" not in page.methods()
    assert not run.shot_dir.exists()
    assert run.gotos() == [url(S1)]


# ------------------------------------------------------------------ guard (AC-C16)


@pytest.mark.parametrize("where", ["pages", "jobs"])
def test_two_human_timeouts_in_a_row_stop_scan(make_run, where):
    if where == "pages":
        page = FakePage(challenge_urls={url(S1), url(S2)})
        searches = [S1, S2, S3]
    else:
        page = FakePage(
            {url(S1): results_html(["k0", "k1", "k2"])},
            descriptions=descs(["k0", "k1", "k2"]),
            challenge_jobs={"k0", "k1"},
        )
        searches = [S1]
    run = make_run(page)

    with pytest.raises(HumanActionTimeout) as info:
        run.scanner.run(searches)

    assert scanner_mod.HUMAN_TIMEOUTS_IN_A_ROW_LIMIT == 2
    assert "2 checks/sign-ins in a row were not solved" in str(info.value)
    assert info.value.snapshot is not None and info.value.snapshot.saved
    assert len(run.lines("  screenshot:")) == 2
    assert len(run.lines("! still blocked")) == 1  # the first one was skipped
    if where == "pages":
        assert run.gotos() == [url(S1), url(S2)]  # s3 never loaded
    else:
        assert ("click", "k2") not in page.calls


def test_timeout_count_resets_after_a_clear_page(make_run):
    ks = keys("b", 3)
    page = FakePage(
        {url(S2): results_html(ks)}, descriptions=descs(ks), challenge_urls={url(S1), url(S3)}
    )
    run = make_run(page)
    stats = run.scanner.run([S1, S2, S3])  # timeout, clear page, timeout: carries on
    assert stats.human_timeouts == 2
    assert run.gotos() == [url(S1), url(S2), url(S3)]
    assert len(run.lines("! still blocked")) == 2
