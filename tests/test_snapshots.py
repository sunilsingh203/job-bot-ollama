"""Failure snapshot helper (`browser.save_snapshot` and friends). Fake page + tmp_path only."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fakes import FakePage
from pydantic import ValidationError

from jobbot.browser import (
    MAX_KEY_CHARS,
    Snapshot,
    display_path,
    prune_snapshots,
    sanitize_job_key,
    save_snapshot,
    snapshot_stem,
    snapshots_to_prune,
)
from jobbot.config import PROJECT_ROOT, BrowserSettings, Settings

WHEN = datetime(2026, 11, 27, 14, 30, 5, 123000)


def fixed_now() -> datetime:
    return WHEN


def collect() -> tuple[list[str], Callable[[str], None]]:
    messages: list[str] = []
    return messages, messages.append


def make_sets(directory: Path, count: int, start: datetime = datetime(2026, 1, 1)) -> list[str]:
    """Create `count` snapshot sets (.png + .html), oldest first. Returns their stems."""
    directory.mkdir(parents=True, exist_ok=True)
    stems = []
    for i in range(count):
        stem = snapshot_stem(start + timedelta(minutes=i), "no_cards")
        (directory / f"{stem}.png").write_bytes(b"PNG")
        (directory / f"{stem}.html").write_text("<html></html>", encoding="utf-8")
        stems.append(stem)
    return stems


def stems_in(directory: Path) -> set[str]:
    return {p.stem for p in directory.iterdir() if p.suffix in (".png", ".html")}


# ------------------------------------------------------------------ naming (AC-C1, AC-C2)


def test_snapshot_stem_format():
    assert snapshot_stem(WHEN, "no_cards") == "20261127-143005-123_no_cards"
    assert (
        snapshot_stem(WHEN, "no_description", "a1b2c3")
        == "20261127-143005-123_no_description_a1b2c3"
    )
    with pytest.raises(ValueError):
        snapshot_stem(WHEN, "../evil")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('../x"y', "xy"),
        ("a/b\\c", "abc"),
        ("k" * 100, "k" * MAX_KEY_CHARS),
        ("", ""),
        (None, ""),
        ("../..", ""),
    ],
)
def test_sanitize_job_key(tmp_path, raw, expected):
    assert sanitize_job_key(raw) == expected
    stem = snapshot_stem(WHEN, "no_description", raw)
    assert stem == (
        f"20261127-143005-123_no_description_{expected}"
        if expected
        else "20261127-143005-123_no_description"
    )
    page = FakePage()
    snap = save_snapshot(
        page,
        tmp_path / "shots",
        "no_description",
        keep=50,
        notify=lambda m: None,
        job_key=raw,
        now=fixed_now,
    )
    assert snap.png is not None
    assert snap.png.parent.resolve() == (tmp_path / "shots").resolve()


# ------------------------------------------------------------------ writing (AC-C3, AC-C4)


def test_save_snapshot_writes_png_and_html(tmp_path):
    directory = tmp_path / "data" / "screenshots"
    assert not directory.exists()
    page = FakePage()
    page.html = "<html><body>héllo</body></html>"
    messages, notify = collect()

    snap = save_snapshot(page, directory, "no_cards", keep=50, notify=notify, now=fixed_now)

    png = directory / "20261127-143005-123_no_cards.png"
    html = directory / "20261127-143005-123_no_cards.html"
    assert snap == Snapshot(png=png, html=html)
    assert png.read_bytes() == b"PNG"
    assert html.read_text(encoding="utf-8") == "<html><body>héllo</body></html>"
    assert len(messages) == 1
    assert messages[0].startswith("  screenshot: ")
    assert str(png.resolve()) in messages[0] and "(+ .html)" in messages[0]


@pytest.mark.parametrize("failure", ["screenshot", "content", "folder"])
def test_save_snapshot_failure_never_raises(tmp_path, failure):
    data_dir = tmp_path / "data"
    if failure == "folder":
        data_dir.write_text("not a folder", encoding="utf-8")  # mkdir under a file fails
    page = FakePage(screenshot_error=failure == "screenshot", content_error=failure == "content")
    messages, notify = collect()

    snap = save_snapshot(
        page, data_dir / "screenshots", "no_cards", keep=50, notify=notify, now=fixed_now
    )

    warnings = [m for m in messages if "! could not save screenshot" in m]
    assert len(warnings) == 1
    assert "Call log" not in warnings[0] and "more detail" not in warnings[0]  # first line only
    if failure == "screenshot":
        assert snap.png is None and snap.html is not None and snap.html.exists()
        assert "png:" in warnings[0]
    elif failure == "content":
        assert snap.html is None and snap.png is not None and snap.png.exists()
        assert "html:" in warnings[0]
    else:
        assert snap == Snapshot()
        assert snap.describe() == "not saved"


def test_save_snapshot_lets_keyboard_interrupt_through(tmp_path):
    class InterruptedPage(FakePage):
        def screenshot(self, path: str, full_page: bool = False, timeout: float = 0) -> bytes:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        save_snapshot(
            InterruptedPage(), tmp_path, "no_cards", keep=50, notify=lambda m: None, now=fixed_now
        )


def test_save_snapshot_window_closed_writes_nothing(tmp_path):
    page = FakePage()
    page.closed = True
    messages, notify = collect()
    snap = save_snapshot(page, tmp_path / "shots", "human_timeout", keep=50, notify=notify)
    assert snap.window_closed and snap.describe() == "none (window closed)"
    assert not (tmp_path / "shots").exists()
    assert page.methods() == ["is_closed"]
    assert messages == ["  no screenshot (window closed)"]


def test_save_snapshot_only_reads_page(tmp_path):
    page = FakePage()
    save_snapshot(page, tmp_path, "dom_fallback", keep=50, notify=lambda m: None, now=fixed_now)
    assert set(page.methods()) <= {"is_closed", "screenshot", "content"}
    assert "screenshot" in page.methods() and "content" in page.methods()


# ------------------------------------------------------------------ retention (AC-C5, AC-C15)


def test_snapshots_to_prune_keeps_newest():
    names = [
        "20260101-000000-000_no_cards.png",
        "20260101-000000-000_no_cards.html",
        "20260102-000000-000_no_description_abc.png",
        "20260103-000000-000_goto_error.html",
        "notes.txt",
        "20260101-000000-000_no_cards.jpg",
        "screenshot.png",
    ]
    assert snapshots_to_prune(names, keep=1) == [
        "20260101-000000-000_no_cards.html",
        "20260101-000000-000_no_cards.png",
        "20260102-000000-000_no_description_abc.png",
    ]
    assert snapshots_to_prune(names, keep=3) == []


def test_prune_keeps_newest_sets_and_ignores_other_files(tmp_path):
    directory = tmp_path / "screenshots"
    stems = make_sets(directory, 52)
    (directory / "notes.txt").write_text("mine", encoding="utf-8")
    messages, notify = collect()

    later = datetime(2026, 2, 1)
    snap = save_snapshot(
        FakePage(), directory, "no_cards", keep=50, notify=notify, now=lambda: later
    )

    assert snap.saved
    expected = set(stems[3:]) | {snapshot_stem(later, "no_cards")}
    assert stems_in(directory) == expected
    assert len(expected) == 50
    assert (directory / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert not [m for m in messages if "!" in m]


def test_prune_error_is_a_warning(tmp_path, monkeypatch):
    directory = tmp_path / "screenshots"
    stems = make_sets(directory, 3)
    stuck = f"{stems[0]}.png"
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == stuck:
            raise PermissionError("file is in use\nsecond line")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    messages, notify = collect()
    prune_snapshots(directory, keep=1, notify=notify)

    assert messages == [f"  ! could not delete old screenshot {stuck}: file is in use"]
    assert stems_in(directory) == {stems[0], stems[2]}  # stems[0].html deleted, .png stuck


def test_screenshots_keep_setting():
    assert BrowserSettings().screenshots_keep == 50
    assert (
        Settings.model_validate({"browser": {"screenshots_keep": 3}}).browser.screenshots_keep == 3
    )
    with pytest.raises(ValidationError):
        BrowserSettings(screenshots_keep=0)


def test_save_snapshot_uses_keep_count(tmp_path):
    directory = tmp_path / "screenshots"
    make_sets(directory, 5)
    save_snapshot(FakePage(), directory, "no_cards", keep=3, notify=lambda m: None, now=fixed_now)
    assert len(stems_in(directory)) == 3
    assert snapshot_stem(WHEN, "no_cards") in stems_in(directory)


# ------------------------------------------------------------------ printed path (A-5)


def test_display_path(tmp_path):
    inside = PROJECT_ROOT / "data" / "screenshots" / "x.png"
    assert display_path(inside) == str(Path("data") / "screenshots" / "x.png")
    outside = tmp_path / "x.png"
    assert display_path(outside) == str(outside.resolve())
    assert Snapshot(png=outside).describe() == str(outside.resolve())
    assert Snapshot(html=outside.with_suffix(".html")).describe().endswith("x.html")
