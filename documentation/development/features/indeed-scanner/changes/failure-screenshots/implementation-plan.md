# Implementation plan: indeed-scanner / failure-screenshots

> Lane B: `features/indeed-scanner/changes/failure-screenshots/implementation-plan.md`

| | |
|---|---|
| Spec / request | [change-definition.md](change-definition.md) (AC-C1..AC-C16), [request.md](request.md), capability [specification.md](../../specification.md) |
| Author | AI agent |
| Date | 2026-11-27 |
| Base commit | `fc9e8e9` (`scanner.py`, `browser.py`, `cli.py`, `config.py` are unchanged since `c3677ba`, so the change definition's line numbers still hold) |
| Build order | **After** `job-store/changes/llm-timeout-stops-run`; **before** `indeed-scanner/changes/scan-cap-and-paging` (planned on top of this one; see section 7, "Rebase notes") |
| Decisions at approval | **OQ-5 guard: yes** (step 7 and AC-C16 are built). **A-8 confirmed.** Decided by the developer in chat, 2026-11-27. Nothing is open. |

Baseline at the base commit (run while planning):

```text
> .venv\Scripts\python -m pytest -q
85 passed in 1.37s
```

## 1. What I understood

When the scanner hits one of five failure points on Indeed (F-1 `goto` error, F-2 results page
with no cards, F-3 DOM fallback, F-4 unreadable description, F-5 `wait_for_human` timeout), it
saves a local **snapshot set** (`<stem>.png` + `<stem>.html`) to `<data_dir>/screenshots/`, prints
the path, keeps only the newest `browser.screenshots_keep` (default 50) sets, and then follows the
per-point rule. F-1 **stops** the scan (clean message, no traceback, exit 0, `--decide` still runs).
F-2, F-3, F-4 behave as today plus the snapshot. F-5 changes behaviour: by the developer's explicit
decision (OQ-4, 2026-11-27) a human-wait timeout now **skips the page or job and carries on**
instead of stopping the scan; a closed window still stops it, and the optional guard (OQ-5) would
stop it after 2 timeouts in a row. Writing a snapshot never crashes the scan, never navigates or
interacts with the page, and never sends anything off the machine. No DB, prompt or schema change.

Decisions in force (all from the developer in chat, 2026-11-27): OQ-1 (snapshot `no_cards` only on
a search's first page or the description-retry reload), OQ-2 (`browser.screenshots_keep`, default
50), OQ-3 (DOM-fallback snapshot once per run + summary line), OQ-4 (skip and carry on), A-1..A-7
accepted. New assumption **A-8** (change definition section 7): skipping a results page after a
timeout ends that search's paging, like F-2. Open: **OQ-5** only.

## 2. Affected layers

| Layer | Impact | Notes |
|---|---|---|
| DB (migrations) | **none** | No table, column, index, status or migration. Latest migration stays `0001_init.sql`. |
| Core logic (`platforms/`, `browser.py`) | yes | Snapshot helper + `PageLoadError` + `Snapshot` in `browser.py` (platform-neutral browser layer). When-to-snapshot and skip logic in `platforms/indeed/scanner.py`. **Nothing in `matcher/`, `llm/`, `pipeline.py`, `resumes/`, `db.py`.** `parse.py` unchanged (no new selector or marker). |
| Interface (CLI `cli.py`, dashboard) | yes | `scan`: new `Scan stopped` handling for `PageLoadError`, screenshot note on stop messages, two summary lines. No new command or flag. No dashboard. `login` unchanged. |
| Config (`config.py`, `config/*.yaml`, `profile.yaml`) | yes | `BrowserSettings.screenshots_keep: int = Field(default=50, ge=1)`; documented in `config/settings.example.yaml`. |
| Prompts (`llm/prompts.py`, version bump?) | none | No prompt or schema change, so no `jobbot eval` run is needed. |
| Safety rules (`CLAUDE.md`) | relaxed by developer decision, no rule text change | OQ-4 relaxes "stop on unsolved check" (tension with rule 3); see section 11. Snapshots local + gitignored (rules 2, 4); sanitised file names (rule 6). |
| Tests | yes | New: `tests/fakes.py` (fake page), `tests/test_snapshots.py`, `tests/test_indeed_scanner.py`, `tests/test_cli_scan.py`. |
| Docs | yes | Section 10. |

## 3. Database changes

**None.** No migration file, no schema or status change, no data rewrite. `data/jobs.db` is not
touched by the snapshot code. New on-disk files are only in `<data_dir>/screenshots/` (already
gitignored through `data/`).

| Migration file | Change | Reversible? |
|---|---|---|
| — | none | — |

## 4. Module interfaces and CLI commands

### 4.1 `src/jobbot/config.py`

```python
class BrowserSettings(BaseModel):
    ...
    # Newest failure snapshot sets (.png + .html) kept in <data_dir>/screenshots/.
    screenshots_keep: int = Field(default=50, ge=1)
```

A value below 1 raises pydantic `ValidationError` at `load_settings` (today that surfaces as a
traceback for any bad settings value; turning it into `ConfigError` is `scan-cap-and-paging` OQ-3,
not this change).

### 4.2 `src/jobbot/browser.py` (snapshot helper: the browser layer, platform-neutral)

Why here: the helper is about "the page currently in the bot's browser", the planned form filler
needs it too, and `browser.py` already owns `Page`-level helpers (`wait_for_human`). It contains
**no Indeed selectors, markers or reason slugs**. It does not import anything from `matcher/`,
`llm/` or `platforms/`, and imports no network library.

New names:

```python
SCREENSHOTS_DIRNAME = "screenshots"
SNAPSHOT_TIMEOUT_MS = 10_000          # A-1: a hung page can't stall the scan for 30 s
MAX_KEY_CHARS = 32
_REASON_RE = re.compile(r"[a-z][a-z_]*")
_STEM_RE = re.compile(r"\d{8}-\d{6}-\d{3}_[a-z][a-z_]*(?:_[A-Za-z0-9]{1,32})?")
_SNAPSHOT_SUFFIXES = (".png", ".html")

@dataclass(frozen=True)
class Snapshot:
    png: Path | None = None
    html: Path | None = None
    window_closed: bool = False
    @property
    def saved(self) -> bool: ...          # png or html written
    def describe(self) -> str: ...
    # "data\screenshots\<stem>.png (+ .html)" | "...\<stem>.html" (PNG failed)
    # | "not saved" | "none (window closed)"

def sanitize_job_key(job_key: str | None) -> str
    # keep [A-Za-z0-9] only, cut to MAX_KEY_CHARS; "" when nothing is left
def snapshot_stem(when: datetime, reason: str, job_key: str | None = None) -> str
    # "<YYYYMMDD-HHMMSS-mmm>_<reason>[_<key>]"; ValueError if reason !~ _REASON_RE
def snapshots_to_prune(names: Iterable[str], keep: int) -> list[str]
    # pure: groups names whose stem matches _STEM_RE and suffix is .png/.html into sets;
    # sorts stems newest first (fixed-width timestamp prefix sorts lexically = in time);
    # returns the file names of every set after the first `keep`. Other names are ignored.
def prune_snapshots(directory: Path, keep: int, notify: Notify) -> None
    # never raises: lists directory (top level only, regular files only), unlinks the names from
    # snapshots_to_prune; each OSError -> "  ! could not delete old screenshot <name>: <first line>"
def display_path(path: Path) -> str
    # A-5: relative to config.PROJECT_ROOT when inside it, else absolute
def save_snapshot(
    page: Page, directory: Path, reason: str, *, keep: int, notify: Notify,
    job_key: str | None = None, now: Callable[[], datetime] = datetime.now,
) -> Snapshot
```

`save_snapshot` contract (the never-crash rule):
1. If `page.is_closed()` is true: print `  no screenshot (window closed)` and return
   `Snapshot(window_closed=True)`. Nothing else is called.
2. Build the stem from `now()` (local time, A-2), `reason` and the sanitised key; create
   `directory` (`mkdir(parents=True, exist_ok=True)`); check that `(directory / stem).resolve()`
   has `directory.resolve()` as its parent (defence in depth for T-13). Any error here: one
   warning, return `Snapshot()`.
3. PNG: `page.screenshot(path=str(png), full_page=True, timeout=SNAPSHOT_TIMEOUT_MS)`.
4. HTML, independently of 3: `html = page.content()`, then `html_path.write_text(html, encoding="utf-8")`.
5. If 3 or 4 failed: **one** line `  ! could not save screenshot: png: <first line>; html: <first line>`
   (only the parts that failed). Only the first line of an error is printed, never page content (T-14).
6. If anything was written: `  screenshot: <describe()>`, then `prune_snapshots(directory, keep, notify)`.
7. Every step catches `Exception` (Playwright errors, `OSError`, `ValueError`), **not**
   `BaseException`, so Ctrl+C still stops the scan.
8. **Read-only:** the only page calls are `is_closed`, `screenshot`, `content`. No `goto`,
   `click`, `fill`, `type`, `press`, `go_back`, `reload`, `bring_to_front`, scrolling or waiting.

Exceptions (in `browser.py`, next to the existing ones):

```python
class HumanActionTimeout(BrowserError):
    def __init__(self, message: str, snapshot: Snapshot | None = None) -> None
    # existing call sites (wait_for_human, login) are unchanged: snapshot defaults to None

class PageLoadError(BrowserError):
    """A results page failed to load (network error, timeout, Chrome error page). Stops the scan."""
    def __init__(self, detail: str, snapshot: Snapshot | None = None) -> None
    # str(e) == f"page load failed: {first line of detail}"
```

`wait_for_human` and `open_browser` are **not changed** (so `jobbot login` is unaffected, A-6).

### 4.3 `src/jobbot/platforms/indeed/scanner.py`

New module constants (the scanner decides *when*; slugs are not Indeed selectors):

```python
REASON_GOTO_ERROR = "goto_error"
REASON_NO_CARDS = "no_cards"
REASON_DOM_FALLBACK = "dom_fallback"
REASON_NO_DESCRIPTION = "no_description"
REASON_HUMAN_TIMEOUT = "human_timeout"
HUMAN_TIMEOUTS_IN_A_ROW_LIMIT = 2   # step 7 only (OQ-5)
```

`ScanStats` gains `dom_fallback_pages: int = 0`, `dom_fallback_snapshot: Snapshot | None = None`,
`human_timeouts: int = 0`.

`IndeedScanner.__init__` gains `self.snapshot_dir = settings.data_dir / SCREENSHOTS_DIRNAME` and
`self._stats = ScanStats()` (and, step 7 only, `self._timeouts_in_a_row = 0`).

Changes per method (kept small on purpose for the rebase of `scan-cap-and-paging`):

| Method | Change |
|---|---|
| `run` | **3 one-line edits, no restructuring:** `stats = self._stats = ScanStats()`; `self._load_results(url, snapshot_if_empty=page_index == 0)`; after `stats.logged_in = ...` add `self._note_dom_fallback(result, stats)`. The `break`/`return` logic and the cap checks are untouched. |
| `_load_results(url, *, snapshot_if_empty: bool = False)` | Wrap only the `goto` line: `except PlaywrightError as e: raise PageLoadError(str(e), self._snapshot(REASON_GOTO_ERROR)) from e` (`PlaywrightTimeout` is a subclass, checked). Replace each of the two `self._handle_blockers()` lines with `if self._check_blockers("page") == "skipped": return None`. After `notify("  no results on this page")`: `if snapshot_if_empty: self._snapshot(REASON_NO_CARDS)`. The rest of the body keeps its indentation. |
| `_process_page` | **No change.** A skipped job comes back from `_read_description` as `None` and takes the existing `! no description` / `description_failures` path. |
| `_read_description` | Replace the `if attempt == 0 and self._handle_blockers():` block with: on attempt 0, `blockers = self._check_blockers("job")`; `"skipped"` -> `return None`; `"waited"` and `self._load_results(results_url, snapshot_if_empty=True) is None` -> `return None` (the reload already reported and snapshotted; the pointless second attempt on an empty page is dropped). After the loop: `self._snapshot(REASON_NO_DESCRIPTION, job_key=jk)` then `return None`. So each job gets at most one snapshot. |
| `_click_and_read`, `_pane_text`, `_blocked*` | No change. |
| `_handle_blockers` | No change (step 7 only: reset `self._timeouts_in_a_row = 0` after both waits return). |

New private methods:

```python
def _snapshot(self, reason: str, job_key: str | None = None) -> Snapshot:
    return save_snapshot(self.page, self.snapshot_dir, reason, job_key=job_key,
                         keep=self.settings.browser.screenshots_keep, notify=self.notify)

def _check_blockers(self, item: Literal["page", "job"]) -> Literal["clear", "waited", "skipped"]:
    # calls _handle_blockers(); on HumanActionTimeout -> _skip_after_human_timeout(e, item),
    # returns "skipped" (that call re-raises when the run must stop)

def _skip_after_human_timeout(self, e: HumanActionTimeout, item: str) -> None:
    snap = self._snapshot(REASON_HUMAN_TIMEOUT)
    if snap.window_closed:
        raise HumanActionTimeout(str(e), snapshot=snap) from e   # stop, as today
    self._stats.human_timeouts += 1
    self.notify(f"  ! still blocked after {timeout:.0f}s - skipped this {item}")
    # step 7 only: count in a row; at HUMAN_TIMEOUTS_IN_A_ROW_LIMIT raise
    # HumanActionTimeout("2 checks/sign-ins in a row were not solved; stopping the scan to
    # protect the Indeed account", snapshot=snap) from e

def _note_dom_fallback(self, result: parse.SearchPage, stats: ScanStats) -> None:
    # result.source == "dom": stats.dom_fallback_pages += 1; on the first one only print
    # "  job JSON missing - reading cards from the page (DOM fallback)" and
    # stats.dom_fallback_snapshot = self._snapshot(REASON_DOM_FALLBACK)
```

Note: the retry reload inside `_read_description` parses a page but is not counted in `stats.pages`
today, so it is not counted for the DOM-fallback line either (consistent with `stats.pages`).

### 4.4 `src/jobbot/cli.py` (`scan` only)

- Import `PageLoadError`.
- Replace `except HumanActionTimeout as e:` with `except (HumanActionTimeout, PageLoadError) as e:`
  placed **before** `except BrowserError` (both subclass it). Output:
  `Scan stopped: <str(e) without trailing '.'>. Screenshot: <e.snapshot.describe()> (progress is saved)`;
  the `Screenshot:` part is left out when `e.snapshot is None`. Exit code 0 (A-3). `stats` stays
  `None`, so no summary (A-4); `--decide` still runs.
- After the existing summary (and `Stopped early` line), when present:
  - `DOM fallback used on N pages (job JSON missing). Screenshot: <describe() or "not saved">`
  - `Skipped after an unsolved check/sign-in: N`
- Every interpolated value goes through `rich.markup.escape`.

| Command | Flags | Output change | Exit |
|---|---|---|---|
| `jobbot scan` | unchanged (`-s`, `--pages`, `--decide`) | `screenshot:` / `! could not save screenshot` / `! still blocked ... skipped this page|job` lines during the scan; `Scan stopped: page load failed: ...` on F-1; two optional summary lines | 0 on F-1 / window closed / guard stops (as today for `HumanActionTimeout`); 1 unchanged for `BrowserError`/`ConfigError` |

## 5. Dashboard screens (if any)

None (dashboard not built).

## 6. Test plan

All tests run without a browser, Indeed or Ollama (M-002). Shared fake in **`tests/fakes.py`**
(imported as `from fakes import FakePage, results_html`; pytest's default `prepend` import mode
puts `tests/` on `sys.path` because it has no `__init__.py`):

- `FakePage`: typed, minimal, mirrors the Playwright calls the scanner makes: `goto`,
  `wait_for_selector`, `locator(sel)` -> `FakeLocator` (`count`, `first`, `click`,
  `scroll_into_view_if_needed`, `inner_html`), `title`, `content`, `url`, `screenshot(path=...,
  full_page=..., timeout=...)` (writes `b"PNG"`), `is_closed`, `bring_to_front`, `go_back`. Each
  call is appended to `page.calls`. Scripted per test: HTML per URL, a set of URLs that raise on
  `goto`, URLs that show a challenge, readable job keys, and flags that make `screenshot` /
  `content` raise `playwright.sync_api.Error`.
- `results_html(job_keys, *, json=True)`: builds a results page with the mosaic JSON (or DOM-only
  cards when `json=False`) and `a[data-jk]` anchors, so a "full page" (>= 10 keys) can be made.
- Scanner tests use `JobStore(tmp_path / "jobs.db")`, `Settings(data_dir=tmp_path / "data")`,
  patch `scanner.human_pause` to a no-op and `time.sleep` (via `monkeypatch`) to a no-op. Timeouts
  use the **real** `wait_for_human` with `browser.human_wait_timeout_s=0` (raises at once on a
  blocked page) or a small value with a fake page that clears or closes after N polls.
- Snapshot tests inject `now=lambda: datetime(2026, 11, 27, 14, 30, 5, 123000)`.

| AC | Test (file::name) or check | Needs LLM? |
|---|---|---|
| AC-C1 naming + folder created | `tests/test_snapshots.py::test_snapshot_stem_format`; `::test_save_snapshot_writes_png_and_html` (folder absent before) | no |
| AC-C2 key sanitising, path stays inside | `tests/test_snapshots.py::test_sanitize_job_key` (parametrised: `../x"y`, `a/b\c`, 100 chars, `""`, `None`) | no |
| AC-C3 PNG + HTML written, one notify line | `tests/test_snapshots.py::test_save_snapshot_writes_png_and_html` | no |
| AC-C4 never crashes | `tests/test_snapshots.py::test_save_snapshot_failure_never_raises` (parametrised: `screenshot` raises -> HTML still written; `content` raises -> PNG still written; `data_dir` is an existing file); `::test_save_snapshot_lets_keyboard_interrupt_through` | no |
| AC-C5 retention | `tests/test_snapshots.py::test_snapshots_to_prune_keeps_newest` (pure); `::test_prune_keeps_newest_sets_and_ignores_other_files` (52 sets + `notes.txt` + one more save -> 50 newest sets, `notes.txt` kept); `::test_prune_error_is_a_warning` (`Path.unlink` patched to raise `OSError` for one file) | no |
| AC-C6 F-1 stops the scan | `tests/test_indeed_scanner.py::test_goto_error_stops_scan_with_snapshot` (parametrised: first `goto`; a later `goto` after one page was stored -> stored rows kept, no further `goto`/`click` in `page.calls`); `::test_goto_error_without_snapshot_still_stops` (`screenshot` and `content` raise -> `PageLoadError.snapshot.describe() == "not saved"`) | no |
| AC-C7 F-1 CLI message | `tests/test_cli_scan.py::test_scan_page_load_error_message` (`CliRunner`; `open_browser`, `IndeedScanner`, `load_settings`, `load_searches`, `_run_decide` monkeypatched in `jobbot.cli`; exit 0, message text, no `Traceback`, decide called with `--decide`) | no |
| AC-C8 F-2 no cards (OQ-1) | `tests/test_indeed_scanner.py::test_no_cards_on_first_page_snapshots_and_continues` (2 searches); `::test_no_cards_after_full_page_is_end_of_results` (10-key page then empty page -> no snapshot); `::test_no_cards_on_retry_reload_snapshots_once` (check clears during a description read, reload empty -> one `no_cards` set, no `no_description` set, job skipped) | no |
| AC-C9 F-3 DOM fallback (OQ-3) | `tests/test_indeed_scanner.py::test_dom_fallback_snapshot_once_per_run` (2 DOM pages -> 1 set, `dom_fallback_pages == 2`, listings stored); summary line in `tests/test_cli_scan.py::test_scan_summary_reports_dom_fallback_and_skips` | no |
| AC-C10 F-4 description unreadable | `tests/test_indeed_scanner.py::test_unreadable_description_snapshots_once_and_moves_on` (one `no_description_<jk>` set, NULL description, `description_failures == 1`, next job read) | no |
| AC-C11 F-5 skip and carry on | `tests/test_indeed_scanner.py::test_human_timeout_on_results_page_skips_page` (challenge on search 1 -> `human_timeout` set, search 2 still loaded, `human_timeouts == 1`, `run` returns); `::test_human_timeout_in_description_skips_job` (job skipped, only a `human_timeout` set, next job attempted); `::test_human_timeout_window_closed_stops_scan` (no files written, `HumanActionTimeout` with `snapshot.window_closed`); CLI: `tests/test_cli_scan.py::test_scan_window_closed_message`; summary: `::test_scan_summary_reports_dom_fallback_and_skips` | no |
| AC-C12 failed snapshot doesn't change the path | `tests/test_indeed_scanner.py::test_failed_snapshot_keeps_scan_path` (parametrised over F-2 and F-4: same rows, counters and `goto` sequence as the succeeding run, plus one warning line) | no |
| AC-C13 read-only snapshot | `tests/test_snapshots.py::test_save_snapshot_only_reads_page` (call log during `save_snapshot` is a subset of `{is_closed, screenshot, content}`); plus code review in `/review-feature` (spec AC-10) | no |
| AC-C14 local and gitignored | Manual, pasted in the review: `git check-ignore -v data/screenshots/x.png` prints the `data/` rule; code review that `browser.py` imports no network module | no |
| AC-C15 keep count from config | `tests/test_snapshots.py::test_screenshots_keep_setting` (default 50; `0` -> `ValidationError`); `::test_save_snapshot_uses_keep_count` (`keep=3` -> 3 sets left) | no |
| AC-C16 guard (**step 7 only**) | `tests/test_indeed_scanner.py::test_two_human_timeouts_in_a_row_stop_scan`; `::test_timeout_count_resets_after_a_clear_page` | no |
| Regression: normal scan writes nothing | `tests/test_indeed_scanner.py::test_json_scan_takes_no_snapshot` (JSON pages, readable descriptions -> no `screenshots/` folder) | no |
| A-5 printed path | `tests/test_snapshots.py::test_display_path` (inside project -> relative; `tmp_path` -> absolute) | no |

**Test count:** 27 new test functions (12 in `test_snapshots.py`, 12 in `test_indeed_scanner.py`,
3 in `test_cli_scan.py`), **+2 if the guard is accepted** (29). Parametrised cases add more
collected items. No `-m llm` tests.

## 7. Implementation steps

0. **Pre-flight.** `/implement-feature` checks that `plan-approval.md` exists and records the
   OQ-5 answer. Confirm `job-store/changes/llm-timeout-stops-run` is merged; rebase on it and
   re-check the line numbers in `cli.py` `scan` (that change edits `_run_decide` and LLM messages,
   not `scan`, so no conflict is expected). Run the baseline `pytest` and note the count.
1. **Config.** Add `BrowserSettings.screenshots_keep` (`config.py`) and document it in
   `config/settings.example.yaml` under `browser:` (`screenshots_keep: 50  # newest failure
   screenshot sets (.png + .html) kept in data/screenshots/`). Tests:
   `test_screenshots_keep_setting`.
2. **Snapshot helper.** In `browser.py`: `Snapshot`, `sanitize_job_key`, `snapshot_stem`,
   `snapshots_to_prune`, `prune_snapshots`, `display_path`, `save_snapshot`, `PageLoadError`,
   `HumanActionTimeout(snapshot=...)`. Add `tests/fakes.py` (only what the snapshot tests need
   first) and `tests/test_snapshots.py` (all 12 tests). Run `pytest`.
3. **Scanner F-1..F-4.** Constants, `ScanStats` fields, `_snapshot`, `_note_dom_fallback`, the
   `goto` wrap, the `no_cards` rule with `snapshot_if_empty`, the 3 one-line edits in `run`, the
   `no_description` snapshot in `_read_description`. Extend `tests/fakes.py` (results pages,
   cards, panes); add the F-1..F-4, AC-C12 and regression tests in `tests/test_indeed_scanner.py`.
4. **Scanner F-5 (skip and carry on).** `_check_blockers`, `_skip_after_human_timeout`, the two
   replacements in `_load_results`, the new attempt-0 block in `_read_description`. Tests:
   the three AC-C11 scanner tests and `test_no_cards_on_retry_reload_snapshots_once`.
5. **CLI.** `PageLoadError` handling and screenshot note in `scan`, the two summary lines.
   Add `tests/test_cli_scan.py` (3 tests).
6. **Lint and tests.** Run the verification commands below; fix everything.
7. **Guard (OQ-5, accepted by the developer 2026-11-27).**
   `HUMAN_TIMEOUTS_IN_A_ROW_LIMIT = 2`, `self._timeouts_in_a_row` (reset when `_handle_blockers`
   returns without raising, and when a description is read); raise in
   `_skip_after_human_timeout` at the limit. Tests: the two AC-C16 tests.
8. **Docs** (section 10), in the same change.
9. **Manual checks.** (a) `git check-ignore -v data/screenshots/x.png` (AC-C14). (b) F-1 end to
   end in real Chrome **without touching Indeed**: in a scratch `config/settings.yaml` set
   `scan.base_url: http://127.0.0.1:9` (closed port), run `jobbot scan -s <name> --pages 1`;
   expect a `goto_error` set in `data/screenshots/` and `Scan stopped: page load failed: ...
   Screenshot: data\screenshots\..._goto_error.png (+ .html) (progress is saved)`, exit 0; then
   restore the setting. Don't provoke checks or failures on the live site.
10. **Mistakes log.** Update `.claude/mistakes/common-mistakes.md`: M-001 (the screenshot promise
    is now true: evidence + streak), M-002 (every new path has a test: streak), M-003 (stop vs skip
    chosen per failure point and tested both ways: streak), M-004 (keep count from config, slugs
    and limits as named constants: streak). Report the changes.

Verification commands (paste the exact output in the review):

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
```

### Rebase notes for `scan-cap-and-paging` (built next, on top of this change)

- `run`: only 3 lines differ (`stats = self._stats = ScanStats()`, the `snapshot_if_empty`
  keyword, the `_note_dom_fallback` call). Paging, the cap check and the between-page pause are
  untouched, so the page-action counting can be added around them unchanged.
- `_load_results`: the `goto` is now inside `try/except PlaywrightError` (count the page action
  before the `try`); the two blocker calls became `_check_blockers("page")`; a new keyword
  `snapshot_if_empty`.
- `_process_page`: unchanged.
- `_read_description`: attempt 0 now returns early on `"skipped"` or an empty reload, and the
  `no_description` snapshot sits after the loop. The reload is still `self._load_results(...)`.
- `ScanStats` gains 3 fields; `cli.py` summary gains 2 lines after `Stopped early`.
- `tests/test_indeed_scanner.py`, `tests/fakes.py` and `tests/test_cli_scan.py` will already exist;
  extend them instead of creating them.

## 8. Risks

- **R-7 (safety, accepted by the developer): more requests while Indeed is challenging the
  account.** After a timeout the scan continues: remaining jobs on the page each wait out their
  own timeout (polling only, no page load), then each further search loads its first page while a
  check may still be up. Mitigation: the guard (step 7, OQ-5). Without it, an unattended scan can
  spend `human_wait_timeout_s` per remaining item.
- **R-4: merge conflict with `scan-cap-and-paging`.** Minimised by the build order and the small
  edits listed in the rebase notes.
- **R-5: fake page drifts from Playwright's API.** Keep `FakePage` minimal and typed; only methods
  the scanner calls. A live manual check (step 9b) exercises the real `screenshot`/`content`.
- **R-1: personal data in snapshots** (signed-in name/email, session tokens in the HTML). Local,
  gitignored, retention-limited, never printed; docs say to scrub before any reuse as a fixture.
- **R-2: disk use** up to ~250 MB at 50 full-page sets; lower `browser.screenshots_keep` if needed.
- **R-3: a failing scan is slower** by up to 10 s per snapshot; snapshots are rare with OQ-1/OQ-3.
- **R-6 / A-7: other uncaught Playwright errors** (e.g. `page.content()` at `scanner.py:100`)
  still end in a traceback with no snapshot.
- **R-8: `full_page=True` in a headed window** may briefly re-layout the page while capturing.
  It does not navigate or send a request. If it ever disturbs Indeed's pane, switch to viewport
  screenshots (A-1 is the only thing to change).
- **R-9: snapshot name collision** (same millisecond, same reason and key) would overwrite one set.
  Practically impossible given the pauses between actions; accepted.
- **R-10: local-time names and DST** could misorder sets around a clock change (none in India);
  retention would at worst keep a slightly older set.

## 9. Open questions and assumptions

- **OQ-5: decided yes** by the developer in chat, 2026-11-27 (step 7, AC-C16). "In a row" = no
  page or job got past a check in between.
- OQ-1..OQ-4 decided by the developer in chat, 2026-11-27 (see the change definition).
- A-1..A-7 accepted. **A-8** (confirmed by the developer, 2026-11-27): skipping a results page
  after a timeout ends that search's paging, like F-2.
- Assumed: `llm-timeout-stops-run` does not touch `scan()` in `cli.py` (checked against its change
  definition; re-check at step 0).
- Assumed: the planned form filler will reuse `save_snapshot`; nothing in this change depends on it.

## 10. Docs to update at implementation time

| Doc | Update |
|---|---|
| `features/indeed-scanner/specification.md` | Section 3: drop "Saving screenshots on failure" from out of scope. Section 4: **amend BR-3** (timeout skips the page/job; window closed stops; guard if accepted) and add a BR for snapshots (points, naming, retention via `browser.screenshots_keep`, never crash, read-only). Section 5: snapshot files + new `ScanStats` fields. Section 6: "Waiting for human -> timeout -> item skipped", "Stopped by page-load error". Section 9: the five rows. Section 10: amend AC-9, AC-20; add the change's ACs (renumbered after AC-21). Section 11: open question 1 resolved; record the OQ-4 decision with its date. |
| `features/indeed-scanner/changelog.md` | Entry for this change (date, summary, ACs, the OQ-4 departure). |
| `architecture/data.md` | `screenshots/` row: written by `browser.save_snapshot` from the scanner; `<YYYYMMDD-HHMMSS-mmm>_<reason>[_<jobkey>].png/.html`; reasons; newest `browser.screenshots_keep` sets kept; may contain the signed-in name/email and session tokens. Config table: `browser.screenshots_keep`. |
| `architecture/security.md` | Assets row "Screenshots" (PNG + HTML, name/email/session tokens). T-4/T-6: a check/sign-in timeout skips the item instead of stopping (developer decision 2026-11-27), never automates past it; guard if accepted. T-9: snapshot built (drop "planned"). T-14: only paths are printed; never paste snapshots into issues, docs, chat or fixtures without scrubbing. |
| `architecture/overview.md` | `browser.py` row: snapshot helper and `PageLoadError`. |
| `.claude/rules/indeed.md` | "Fail loudly" line: the five points, what is saved, retention, never crash. "Pause on challenge" line: a timeout skips the item (window closed / guard stops). |
| `.claude/rules/safety.md` | No text change (rule 3 "pause and ask the user" still holds). |
| `config/settings.example.yaml` | `browser.screenshots_keep` (step 1). |
| `CLAUDE.md` | "Indeed scanning" bullets (timeout behaviour, screenshots now real). **Ask the developer before editing.** |
| `.claude/mistakes/common-mistakes.md` | Step 10. |

`README.md`: no change (no new command or flag).

## 11. Safety rules (`.claude/rules/safety.md`)

1. **Never auto-submit:** not touched (scanner only).
2. **Everything stays local:** snapshots go to `<data_dir>/screenshots/`; the helper makes no
   network call and imports no network library (AC-C14).
3. **Protect the Indeed account:** headed persistent Chrome unchanged; pacing and caps unchanged;
   a snapshot loads no page and only reads the current one (AC-C13); every check still waits for
   the human and is never automated past (spec AC-10). **Relaxed by explicit developer decision
   (OQ-4):** a timed-out check no longer stops the scan. Recorded in the change definition,
   section 4.1, and R-7; the guard (OQ-5) is offered to limit it.
4. **Personal data gitignored:** `data/` is ignored; snapshot content is never printed, committed
   or used as a fixture without scrubbing; tests use fake pages and `tmp_path` only.
5. **Never invent facts on a form:** not touched.
6. **Untrusted input:** the scraped job key is sanitised to `[A-Za-z0-9]{0,32}` before it goes
   into a file name, and the resolved path is checked to stay inside the folder (AC-C2). The reason
   slug comes only from code constants and is validated. HTML is written as data, never parsed or
   executed by the helper.
7. **Approval files:** this plan does not create `plan-approval.md`; the developer writes it.

## 12. ADRs

- **Needed: none.** The OQ-4 departure is a capability behaviour choice inside safety rule 3
  (the bot still pauses for the human and never bypasses a check); it is recorded in the spec,
  `security.md` and this change folder.
- Related: [ADR-0001](../../../../decisions/ADR-0001-local-only-llm.md) (local only: snapshots
  never leave the machine), [ADR-0002](../../../../decisions/ADR-0002-keep-src-layout.md) (helper in
  `src/jobbot/browser.py`), [ADR-0003](../../../../decisions/ADR-0003-sql-migration-files.md) (no
  migration needed), [ADR-0004](../../../../decisions/ADR-0004-human-approval-never-auto-submit.md)
  (unaffected).
