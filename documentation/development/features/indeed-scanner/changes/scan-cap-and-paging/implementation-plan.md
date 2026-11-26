# Implementation plan: indeed-scanner / scan-cap-and-paging

> Lane B: `features/indeed-scanner/changes/scan-cap-and-paging/implementation-plan.md`

| | |
|---|---|
| Spec / request | [change-definition.md](change-definition.md), [request.md](request.md), capability [specification.md](../../specification.md) |
| Author | AI agent |
| Date | 2026-11-27 |
| Base commit | `fc9e8e9` (working tree; `scanner.py`, `config.py`, `cli.py`, `parse.py` unchanged since `c3677ba`) |
| Status | **Draft. Do not approve yet: `PAGE_STEP` / `FULL_PAGE_SIZE` wait for the real scan on 2026-11-28 (OQ-1).** |
| Build order | **Last** of the three open changes: after `job-store/changes/llm-timeout-stops-run` and `indeed-scanner/changes/failure-screenshots`, and after the real scan has settled OQ-1 (see section 7, step 0) |

File:line references are to the base commit. `failure-screenshots` edits the same scanner
functions, so step 1 refreshes every reference against the code as it stands after that change.

---

## 1. What I understood

One per-run cap, `scan.max_page_actions_per_run` (default 80), replaces `scan.max_new_jobs_per_run`
and bounds **every Indeed request the scanner starts**: each results-page `goto` (including empty
pages, challenge pages and the reload after a human wait) and each description attempt (click,
already-open pane read, or a `/viewjob` page plus its `go_back`, including the retry). An action is
counted *before* it starts. When none is left the action is refused, the scan stops cleanly
(`run` returns, no further pause/load/click, `--decide` still runs, exit 0) and the summary says
so. The old key is rejected with a `ConfigError` telling the user to rename it; `ScanSettings`
forbids unknown keys; `load_settings` turns pydantic `ValidationError` into `ConfigError`.
Date-sorted searches stop paging when a page has nothing new and nothing left to read. Paging uses
two named Indeed constants in `parse.py` (`PAGE_STEP`, `FULL_PAGE_SIZE`) whose values come from the
developer's real scan. Actions after a "skip and carry on" (the `failure-screenshots` behaviour
after a `wait_for_human` timeout) count like any other.

### Assumptions and checks
- **A-1 (checked):** `config/settings.yaml` does **not** exist in the working tree on 2026-11-27
  (only existence was checked; the file was not opened). So nothing breaks today; risk R-1 covers a
  file created later.
- **A-2 (checked):** no test builds `ScanSettings` or `Settings` with extra keys
  (`rg "Settings" tests` finds only `MatchingSettings` in `tests/test_filters.py:3,34`). `extra="forbid"`
  on `ScanSettings` breaks no existing test. `Profile` keeps `extra="allow"` (`config.py:110`).
- **A-3:** `extra="forbid"` applies to **`ScanSettings` only**, as recommended and decided. `llm`,
  `matching`, `browser` and the top-level `Settings` keep pydantic's default (`ignore`). Reason: the
  safety-relevant keys live in `scan`, and forbidding elsewhere could break the developer's future
  `settings.yaml` for keys that are harmless. Widening it is a separate change (section 9).
- **A-4:** the `ValidationError` -> `ConfigError` wrapping is in `load_settings` and therefore covers
  **all** sections. Commands that already catch `ConfigError` around `load_settings` (`scan`
  `cli.py:319-323`, `resumes index/show` `cli.py:64-79, 85-90`, `match`/`eval` via `_build_matcher`
  `cli.py:175-180, 203-231`) now print a clean `Error:` line. Commands that call `load_settings`
  outside a `try` (`login` `cli.py:266`, `decide` `cli.py:363`, `jobs` `cli.py:406`, `show`
  `cli.py:439`) still end in a traceback, now of a `ConfigError` with a readable message instead of
  a `ValidationError`. Not worse than today; wrapping them is out of scope (section 9).
- **A-5:** a description attempt counts even when the card is gone and no click is made
  (`scanner.py:162-163`). "Every attempt counts" is the simplest rule to test and errs on the safe
  side (change-definition BR-C1).
- **A-6:** the internal stop signal is a private exception `_CapReached` raised by the counting
  helper and caught only in `IndeedScanner.run`. It never leaves `run`, so the CLI contract is
  unchanged.
- **A-7:** a job whose retry is refused by the cap is **not** counted in `description_failures` (it
  was cut, not failed) and gets no `no_description` snapshot (`failure-screenshots` takes that only
  after the second attempt fails). It keeps a NULL description and is read on a later run (BR-6).
- **A-8:** the per-search page notice (`[name] page k/N`) is printed only after the load has been
  allowed, so a refused load prints no misleading "page k/N" line.

### Spec gaps / conflicts found
- `failure-screenshots/change-definition.md` OQ-4 still recommends *stop* after a `wait_for_human`
  timeout, while the developer decided *skip and carry on* in chat. Its plan (being written in
  parallel) is the source of truth for the skip paths. This plan does not depend on which item is
  skipped, only on every later action going through the counting helper (AC-C18). Step 1 re-checks
  this against the built code.
- The window-closed case (`HumanActionTimeout("The browser window was closed.")`) cannot carry on.
  Whatever `failure-screenshots` does there, no further action is counted because none can be made.

## 2. Affected layers

| Layer | Impact | Notes |
|---|---|---|
| DB (migrations) | none | No schema, status or `data/` change. Latest migration stays `0001_init.sql` |
| Core logic (`platforms/`) | yes | `platforms/indeed/scanner.py` (counting, cap, clean stop, early stop, paging), `platforms/indeed/parse.py` (two Indeed paging constants). Nothing in `matcher/`, `llm/`, `pipeline.py` |
| Interface (CLI `cli.py`, dashboard) | yes (CLI output only) | `jobbot scan` summary line and `Stopped early` text. No flag, command or exit-code change. No dashboard |
| Config (`config.py`, `config/*.yaml`) | yes | New key, old key rejected, `ScanSettings` `extra="forbid"`, `ValidationError` -> `ConfigError`. `settings.example.yaml`, `searches.yaml` comment |
| Prompts (`llm/prompts.py`) | none | No version bump, no `jobbot eval` needed |
| Safety rules (`CLAUDE.md`) | tightened | Rule 3 (account protection): the cap now bounds all bot-initiated Indeed requests. `CLAUDE.md:105` names the old key; editing it **needs the developer's OK** |
| Tests | yes | New `tests/test_config.py`, `tests/test_indeed_scanner.py` (or extend the one `failure-screenshots` creates), `tests/test_cli_scan.py` (or extend), update `tests/test_indeed_parse.py` |
| Docs | yes | indeed-scanner spec, changelog, as-built plan section 3, `architecture/security.md` T-4, `architecture/data.md` settings row, `.claude/rules/indeed.md:7`, `CLAUDE.md:105` (with OK), `documentation/customer/indeed-observations.md` (new), `.claude/mistakes/common-mistakes.md` M-004 |

## 3. Database changes

None. No migration file, no table/column/index/constraint change, no status change, nothing new in
`data/`. Jobs left with a NULL description by a capped run are read on a later run, as today.

### Config changes (instead of DB changes)

| Item | Change |
|---|---|
| `scan.max_page_actions_per_run` | **New.** `int`, `ge=1`, default `80`. Cap on result-page loads + description reads per `jobbot scan` run |
| `scan.max_new_jobs_per_run` | **Removed.** Present in a settings file -> `ConfigError`: renamed, new meaning, rename it in `config/settings.yaml`. No alias |
| `ScanSettings.model_config` | `ConfigDict(extra="forbid")`: any unknown key under `scan:` -> `ConfigError` naming `scan.<key>` |
| Other sections | Unchanged (`extra` stays `ignore`) |
| `load_settings` | Catches `pydantic.ValidationError` and raises `ConfigError` listing each bad key by dotted path |

## 4. Module interfaces and CLI commands

### 4.1 `src/jobbot/config.py`
```python
from pydantic import BaseModel, ConfigDict, Field, ValidationError

class ScanSettings(BaseModel):
    # Unknown keys fail loudly: a typo in this safety cap must never fall back to the default.
    model_config = ConfigDict(extra="forbid")

    base_url: str = "https://in.indeed.com"
    delay_min_s: float = 2.5
    delay_max_s: float = 6.0
    # Cap on Indeed page actions per `jobbot scan`: every result-page load plus every description
    # read (retries and reloads included). The scan stops cleanly when it is reached.
    max_page_actions_per_run: int = Field(default=80, ge=1)

# Keys that were renamed, as dotted paths -> what to tell the user. Checked before the generic
# "unknown key" message so an old settings file gets a precise instruction.
RENAMED_SETTINGS: dict[str, str] = {
    "scan.max_new_jobs_per_run": (
        "was renamed to scan.max_page_actions_per_run. The new cap counts every Indeed page action "
        "(result-page loads + description reads), so choose the number again (default 80) and "
        "rename the key"
    ),
}

def _settings_error(path: Path, err: ValidationError) -> str:
    """One line per bad key, by dotted path. Never echoes the input values."""

def load_settings(path: Path | None = None) -> Settings:
    """... Raises ConfigError (not ValidationError) for invalid or unknown settings."""
    path = path or CONFIG_DIR / "settings.yaml"
    try:
        settings = Settings.model_validate(read_yaml(path)) if path.exists() else Settings()
    except ValidationError as e:
        raise ConfigError(_settings_error(path, e)) from e
    ...  # unchanged path fix-ups and JOBBOT_MODEL override
```
`_settings_error` output format (one header line, one `- ` line per error):
```
Invalid D:\...\config\settings.yaml:
- scan.max_new_jobs_per_run: was renamed to scan.max_page_actions_per_run. ... rename the key in D:\...\config\settings.yaml.
- scan.max_page_actions_per_run: Input should be greater than or equal to 1
- scan.max_page_action_per_run: unknown key (check the spelling against config/settings.example.yaml)
```
Rules: `loc` joined with `.`; `type == "extra_forbidden"` -> `RENAMED_SETTINGS[key]` + " in <path>."
if present, else the "unknown key" text; any other error -> pydantic's `msg`. `input` is not
printed (settings hold no secrets today, but the rule keeps the message format safe). Raised
`ConfigError`s from `read_yaml` (bad YAML) are unchanged.

### 4.2 `src/jobbot/platforms/indeed/parse.py`
```python
# Paging on in.indeed.com, observed on 2026-11-28 (documentation/customer/indeed-observations.md).
# Indeed facts, not user settings. Change only after a new real-scan check.
PAGE_STEP = <verified>       # `start` increment between result pages (Indeed's own "Next" link)
FULL_PAGE_SIZE = <verified>  # distinct listings on a full results page; fewer = last page
```
Placed next to the other Indeed facts (`parse.py:20-32`). `parse.py` stays pure. If the real scan
shows that sponsored cards make the page size vary, the step records whether `FULL_PAGE_SIZE` is
compared against all distinct listings (today's `result.listings`) or non-sponsored ones only; the
default is all listings, which is what `scanner.py:82` compares today.

### 4.3 `src/jobbot/platforms/indeed/scanner.py`

**Removed:** `RESULTS_PER_PAGE_STEP` (`:25`), `_cap_reached` (`:138-139`).

**`search_url`** (`:42-49`): `params["start"] = page_index * PAGE_STEP` (imported from `parse`).
Signature unchanged; `jobbot login` (`cli.py:268`, page index 0) unaffected.

**`ScanStats`** (`:29-39`):
```python
@dataclass
class ScanStats:
    result_page_loads: int = 0     # every results-page goto, incl. empty pages and reloads (was `pages`)
    description_reads: int = 0     # every description attempt, incl. retries and already-open reads
    action_cap: int = 0            # scan.max_page_actions_per_run for this run
    listings_seen: int = 0
    new_jobs: int = 0
    descriptions: int = 0          # descriptions read successfully (unchanged meaning)
    description_failures: int = 0
    duplicates: int = 0
    logged_in: bool | None = None
    per_search: dict[str, int] = field(default_factory=dict)
    stopped_early: str | None = None

    @property
    def page_actions(self) -> int:
        return self.result_page_loads + self.description_reads
```
`pages` is renamed to `result_page_loads` because its meaning changes (every load, not only loads
with listings) and the name must say what it counts (M-004). Only `cli.py` reads it.

**Counting helpers** (new, private):
```python
class _CapReached(Exception):
    """Internal: the per-run page-action cap refused an action. Caught only in `run`."""

RESULTS = "results"
DESCRIPTION = "description"

def _start_action(self, kind: str) -> None:
    """Count one Indeed page action *before* it starts. Raise _CapReached if none is left."""
    s = self.stats
    if s.page_actions >= s.action_cap:
        s.stopped_early = (
            f"reached scan.max_page_actions_per_run={s.action_cap} "
            f"({s.result_page_loads} result pages, {s.description_reads} description reads)"
        )
        raise _CapReached
    if kind == RESULTS:
        s.result_page_loads += 1
    else:
        s.description_reads += 1

def _actions_left(self) -> bool:
    return self.stats.page_actions < self.stats.action_cap
```
`stopped_early` is set **only** at a refusal, which fixes the reporting gap (change-definition 1.1):
a run whose work used exactly the cap and needed nothing more is not "stopped early" (AC-C9).

**Counting points** (the only places that start an Indeed request):

| Point | Today | After |
|---|---|---|
| Results `goto` | `_load_results` `:90` | `_start_action(RESULTS)` is the first line of `_load_results`, before `goto`. All callers go through it: the page loop in `run` and the reload after a human wait (`:152-154`), plus any reload `failure-screenshots` adds |
| Description attempt | `_read_description` loop `:144-146` | `_start_action(DESCRIPTION)` at the top of each loop turn, before `_click_and_read` (covers click, already-open read, `/viewjob` + `go_back`, card missing) |
| `go_back` + `wait_for_selector` after `/viewjob` | `:176-177` | Not counted: part of the same read (OQ-5) |
| `wait_for_human` polling | `browser.py:76-83` | Not counted. `browser.py` is not changed |
| Failure snapshot (`failure-screenshots`) | n/a | Not counted (reads the page only) |

Invariant checked in every scanner test: `fake.gotos == stats.result_page_loads` and
`calls to _click_and_read == stats.description_reads`.

**`run`** (`:62-85`), restructured so the stop is clean from any depth:
```python
def run(self, searches: list[Search], max_pages: int | None = None) -> ScanStats:
    self.stats = ScanStats(action_cap=self.settings.scan.max_page_actions_per_run)
    try:
        for search in searches:
            self._run_search(search, max_pages or search.max_pages)
    except _CapReached:
        pass  # clean stop: stopped_early is set; every write so far is already committed
    return self.stats

def _run_search(self, search: Search, pages: int) -> None:
    stats = self.stats
    stats.per_search[search.name] = 0
    for page_index in range(pages):
        url = search_url(self.base_url, search, page_index)
        result = self._load_results(url, label=f"[{search.name}] page {page_index + 1}/{pages}")
        if result is None or not result.listings:
            break
        stats.logged_in = result.logged_in
        outcome = self._process_page(result, search, url)
        if len(result.listings) < FULL_PAGE_SIZE:
            break  # last page
        if search.sort == "date" and outcome.new == 0 and outcome.needed_description == 0:
            self.notify(f"  [{search.name}] nothing new on page {page_index + 1} (sorted by date); "
                        "skipping its later pages")
            break  # BR-C7 / OQ-4
        if page_index + 1 < pages and self._actions_left():
            human_pause(self.settings.scan.delay_min_s * 2, self.settings.scan.delay_max_s * 2)
```
Changes against today: the cap check at the loop top (`:68-72`) is gone (the helper refuses the
load instead); the between-page pause (`:84`) runs only when another page of this search will be
loaded and an action is left, so no pause precedes a refused action or follows the last page;
`stats.pages += 1` (`:78`) is replaced by the count in `_start_action`; per-search counting moves
into `_process_page` so it is not lost when the cap stops mid-page.

**`_load_results(url, label=None)`** (`:89-100`): `self._start_action(RESULTS)` first; then
`self.notify(label)` if given; then today's body. A load that ends in "no results" still counted.

**`_process_page`** (`:102-136`) returns a small private dataclass instead of an `int`:
```python
@dataclass
class _PageOutcome:
    new: int                    # listings stored for the first time
    needed_description: int     # listings (new or old) still without a description before reading
```
Body: upsert every listing first (unchanged, so a cap stop mid-page keeps them all), adding to
`stats.new_jobs` and `stats.per_search[search.name]`; then build the list of listings for which
`store.needs_description` is true (`needed_description = len(todo)`); then read each (the
`_cap_reached` check at `:119-120` is removed; `_read_description` may raise `_CapReached`). The
pause after each attempt (`:135`) runs only `if self._actions_left()`. Success/failure handling and
notify lines unchanged.

**`_read_description`** (`:143-155`):
```python
for attempt in range(2):
    self._start_action(DESCRIPTION)          # retries count (OQ-5)
    ...  # unchanged try/_click_and_read
    if text:
        return text
    if attempt == 0 and self._handle_blockers():
        self._load_results(results_url)      # counted as a result-page load (OQ-5)
return None
```
If the cap refuses the reload or the retry, `_CapReached` propagates: no `description_failures`
increment, no snapshot, NULL description kept (A-7). The skip-on-timeout handling that
`failure-screenshots` adds around `_handle_blockers` stays as built; any `goto`/`reload`/click it
makes must go through `_load_results` / `_read_description` so it is counted (step 1 checks; AC-C18).

`_click_and_read`, `_pane_text`, the blocker helpers and `DESCRIPTION_TIMEOUT_S` are unchanged.

**Exceptions:** `run` raises nothing new. `_CapReached` must not be raised inside any `try` that
catches `Exception` (e.g. the snapshot writer's own guard from `failure-screenshots`, or the
`PlaywrightError` handler at `:145-149`, which only catches `PlaywrightError` and is fine). Step 5
checks this; AC-C6/AC-C8 tests would fail if it were swallowed.

### 4.4 `src/jobbot/cli.py` (`scan`, `:343-352`)
```python
signed = {True: "yes", False: "no", None: "unknown"}[stats.logged_in]
console.print(
    f"\n[bold]Scan done:[/] {stats.result_page_loads} pages, {stats.listings_seen} listings, "
    f"{stats.new_jobs} new jobs, {stats.descriptions} descriptions read, "
    f"{stats.description_failures} failed, {stats.duplicates} duplicates | "
    f"page actions: {stats.page_actions}/{stats.action_cap} | signed in: {signed}"
)
if stats.stopped_early:
    console.print(f"[yellow]Stopped early:[/] {escape(stats.stopped_early)}")
```
Printed text when capped:
`Stopped early: reached scan.max_page_actions_per_run=80 (14 result pages, 66 description reads)`.
No flag changes; exit code 0; `--decide` still runs after (unchanged flow `:353-354`). A bad or
old config key exits 1 through the existing `except ConfigError` (`:322-323`) before the browser
opens. Whatever `failure-screenshots` adds to this function (screenshot lines, page-load stop) is
kept; only the two statements above change.

## 5. Dashboard screens

None.

## 6. Test plan

No test opens a browser or hits Indeed. No test needs the LLM (`-m llm` not used).

**Scanner test harness** (`tests/test_indeed_scanner.py`; if `failure-screenshots` already created
this file and a fake page, extend that fake instead of adding a second one):
- `FakeSite`: per search query, a map `start -> list[FakeJob]` (`jk`, title, company, behaviour:
  `ok` | `fail` | `viewjob` | `challenge_once` | `missing`). Distinct description text per job, so
  `set_description` never marks a duplicate by accident.
- `FakePage`: `goto` (records the URL, picks the listing set from `q` and `start`), `url`,
  `content()` (results HTML built with the real `MOSAIC_MARKER` JSON + `a[data-jk]` anchors, so
  `parse_search_page` runs unmodified and returns `source="json"`), `title()`, `locator(sel)` for
  `SEL_CARD_LINK`, `SEL_CARD_LINK[data-jk=...]` and `SEL_DESCRIPTION` (`count`, `first`,
  `scroll_into_view_if_needed`, `click`, `inner_html`), `wait_for_selector`, `go_back`,
  `bring_to_front`, `is_closed`. Records `gotos`, `clicks`, `go_backs`. Option to auto-open the
  first card (URL gains `vjk=`), to test the already-open read.
- `FakeClock` patched over `jobbot.platforms.indeed.scanner.time` and `jobbot.browser.time`
  (`monotonic()`, `sleep()` advances the clock), so the 15 s description wait and `wait_for_human`
  polling run instantly and deterministically.
- `human_pause` patched in `jobbot.platforms.indeed.scanner` with a recorder.
- A spy on `IndeedScanner._click_and_read` counting attempts.
- Real `JobStore(tmp_path / "jobs.db")`; `Settings(data_dir=tmp_path, ...)` with
  `ScanSettings(max_page_actions_per_run=N)`.
- Helper `assert_counts(fake, spy, stats)`: `fake.gotos == stats.result_page_loads`,
  `spy.calls == stats.description_reads`, `stats.page_actions <= stats.action_cap`.
- Tests use `FULL_PAGE_SIZE` from `parse` to size "full" pages, so they hold for the verified value.

| AC | Test (file::name) or check | Needs LLM? |
|---|---|---|
| AC-C1 | `tests/test_config.py::test_page_action_cap_defaults_to_80` (no file; file without `scan:`) | no |
| AC-C1 | `tests/test_config.py::test_page_action_cap_read_from_settings` (7) | no |
| AC-C1 | `tests/test_config.py::test_scan_settings_has_no_old_cap_field` | no |
| AC-C2 | `tests/test_config.py::test_invalid_page_action_cap_is_config_error[0, -1, abc]` (names `scan.max_page_actions_per_run` and the file) | no |
| AC-C2 | `tests/test_config.py::test_invalid_value_in_other_section_is_config_error` (`llm.timeout_s: abc`) | no |
| AC-C2 | `tests/test_cli_scan.py::test_scan_bad_config_exits_1_without_opening_browser` (real `load_settings`, `jobbot.config.CONFIG_DIR` monkeypatched to `tmp_path`; `open_browser` patched to fail) | no |
| AC-C3 | `tests/test_config.py::test_old_cap_key_rejected_with_rename_message[alone, with_new_key]` | no |
| AC-C3 | `tests/test_config.py::test_misspelt_scan_key_rejected` | no |
| AC-C3 | `tests/test_config.py::test_unknown_key_in_other_section_still_ignored` (`llm.foo`) | no |
| AC-C4 | `tests/test_indeed_scanner.py::test_result_page_loads_counted_including_empty_page` | no |
| AC-C5 | `tests/test_indeed_scanner.py::test_every_description_attempt_counted` (ok, fail, `/viewjob` + `go_back`, already open, card missing) | no |
| AC-C6 | `tests/test_indeed_scanner.py::test_cap_is_a_hard_limit[1, 3, more_than_needed]` | no |
| AC-C7 | `tests/test_indeed_scanner.py::test_old_rows_without_description_cost_a_read_finished_rows_do_not` | no |
| AC-C8 | `tests/test_indeed_scanner.py::test_cap_stop_is_clean` (no `goto`/click/`human_pause` after the refusal; rows stored; earlier descriptions kept; `per_search` kept; `stopped_early` text) | no |
| AC-C9 | `tests/test_indeed_scanner.py::test_stopped_early_only_when_an_action_was_refused[exact_cap, cap_minus_1, last_page_of_last_search]` | no |
| AC-C10 | `tests/test_cli_scan.py::test_scan_summary_shows_page_actions` (`open_browser` and `IndeedScanner` patched, `load_settings` patched to a `tmp_path` `Settings`) | no |
| AC-C10 | `tests/test_cli_scan.py::test_scan_stopped_early_line_exit_0_and_decide_runs` (`_run_decide` patched to record) | no |
| AC-C10 | `tests/test_cli_scan.py::test_scan_no_stopped_early_line_when_not_capped` | no |
| AC-C11 | `tests/test_indeed_scanner.py::test_retry_and_reload_after_human_wait_are_counted` (first click shows a challenge that clears after several polls; 2 reads + 1 reload; polls add nothing) | no |
| AC-C11 | `tests/test_indeed_scanner.py::test_cap_between_attempts_refuses_reload_or_retry[before_reload, before_retry]` | no |
| AC-C12 | `tests/test_indeed_parse.py::test_search_url` (updated: `start={2 * PAGE_STEP}`; no `start` for index 0) | no |
| AC-C12, AC-C13 | `tests/test_indeed_parse.py::test_paging_constants_match_real_scan` (pins both values; comment points to `indeed-observations.md`) | no |
| AC-C12 | Review check: `rg "RESULTS_PER_PAGE|\b10\b|\b15\b" src/jobbot/platforms/indeed/scanner.py` finds no page-size literal | no |
| AC-C13 | `tests/test_indeed_scanner.py::test_paging_continues_on_full_page_and_stops_on_short_page` (`max_pages: 3`; exactly 2 loads) | no |
| AC-C14 | `tests/test_indeed_scanner.py::test_pages_option_and_empty_page_bound_paging` (`max_pages` override; empty page 2 of search A counts 1 action; search B still loaded) | no |
| AC-C15 | Review check: `rg max_new_jobs_per_run` and `rg "15 jobs|RESULTS_PER_PAGE"` over the repo; read every file in section 7 step 10 | no |
| AC-C16 | Manual, developer: `scan.max_page_actions_per_run: 5`, `jobbot scan -s <one search>`; at most 5 visible loads/clicks, `page actions: 5/5`, `Stopped early` line if work was left. Result in `review.md` | no |
| AC-C17 | `tests/test_indeed_scanner.py::test_date_search_stops_after_page_with_nothing_new` | no |
| AC-C17 | `tests/test_indeed_scanner.py::test_relevance_search_does_not_stop_early` | no |
| AC-C17 | `tests/test_indeed_scanner.py::test_date_page_with_pending_description_keeps_paging` | no |
| AC-C18 | `tests/test_indeed_scanner.py::test_actions_after_human_timeout_skip_are_counted[description, results_page]` (`wait_for_human` patched to raise `HumanActionTimeout` once; written against `failure-screenshots` as built) | no |

Totals: **28 named tests** (27 new, 1 updated): 14 in `test_indeed_scanner.py`, 8 in
`test_config.py`, 4 in `test_cli_scan.py`, 2 in `test_indeed_parse.py`. Several are parametrised
(more cases at run time). Plus 2 manual/review checks (AC-C15, AC-C16) and 1 grep check (AC-C12).
Every AC from AC-C1 to AC-C18 is covered.

`tests/test_cli_scan.py` must never touch the real `data/` (testing standard): the summary tests
patch `jobbot.cli.load_settings` to return `Settings(data_dir=tmp_path, config_dir=<tmp with a
searches.yaml>)`; the bad-config test fails inside `load_settings`, before any store is opened. If
`failure-screenshots` already created a CLI test module, add these tests there instead.

## 7. Implementation steps

0. **Preconditions (stop if any is missing).**
   - `job-store/changes/llm-timeout-stops-run` and `indeed-scanner/changes/failure-screenshots`
     are implemented and merged (both touch `cli.py`; `failure-screenshots` rewrites parts of
     `scanner.py` and adds the first scanner tests). Rebase this branch on them.
   - The developer's real scan (2026-11-28) is done and the checklist in change-definition OQ-1 is
     filled in: cards per full page, `start` step of Indeed's own "Next" link, overlap, last-page
     behaviour, sponsored cards, any check seen.
   - `plan-approval.md` exists, written by the developer (never by Claude).
1. **Refresh against the built code.** Re-read `scanner.py`, `cli.py`, `browser.py` and the
   `failure-screenshots` plan/review. List every request the scanner starts:
   `rg -n "\.goto\(|\.click\(|\.reload\(|go_back\(" src/jobbot/platforms/indeed/scanner.py`.
   Map each to a counting point in section 4.3 (or "part of the same read"). Note how the
   skip-after-timeout paths continue (next card, next page, next search, reload?) and confirm each
   continues through `_load_results` / `_read_description`. Update file:line refs in this plan's
   working notes; if a path does not fit, stop and ask.
2. **Set the constants from the real-scan checklist results.** Write
   `documentation/customer/indeed-observations.md` (dated 2026-11-28) from the developer's notes,
   with no personal data. Add `PAGE_STEP` and `FULL_PAGE_SIZE` to `parse.py` with the observed
   values, the date and a pointer to that note. Record there whether sponsored cards count toward
   `FULL_PAGE_SIZE` (section 4.2). Update `config/searches.yaml:5` to the observed jobs per page.
3. **Config, tests first.** Write `tests/test_config.py` (8 tests, section 6); run it, see the
   failures; then change `ScanSettings`, add `RENAMED_SETTINGS`, `_settings_error`, and the
   `try/except ValidationError` in `load_settings` (section 4.1). Run the file again.
4. **`config/settings.example.yaml`:** replace line 30 with
   `max_page_actions_per_run: 80   # cap per jobbot scan: result-page loads + description reads (retries count)`
   and add a comment above `scan:` that unknown `scan` keys are rejected.
5. **Scanner.** In `scanner.py`: remove `RESULTS_PER_PAGE_STEP` and `_cap_reached`; import
   `PAGE_STEP`, `FULL_PAGE_SIZE`; update `search_url`; new `ScanStats` fields and property;
   `_CapReached`, `_start_action`, `_actions_left`, `_PageOutcome`; restructure `run` /
   `_run_search`; `_load_results(url, label=None)`; `_process_page`; `_read_description`
   (section 4.3). Check that `_CapReached` is never inside an `except Exception`.
6. **Scanner tests.** Build or extend the fake page harness and write the 14
   `test_indeed_scanner.py` tests (section 6). Every test asserts `assert_counts`.
7. **Parse tests.** Update `tests/test_indeed_parse.py::test_search_url` (`:95-98`) to use
   `PAGE_STEP`; add `test_paging_constants_match_real_scan`.
8. **CLI.** Change the summary and `Stopped early` lines in `cli.py` (section 4.4). Write the 4
   tests in `tests/test_cli_scan.py` (AC-C2 bad config, AC-C10 x3).
9. **Verify** (paste each command and its summary line into the task report; never claim a run
   that did not happen):
   ```powershell
   .venv\Scripts\python -m pytest
   .venv\Scripts\ruff check src tests
   .venv\Scripts\ruff format --check src tests
   ```
10. **Docs that must agree** (same change):
    - `features/indeed-scanner/specification.md`: BR-8 -> BR-C1..C4, C6; BR-9 -> BR-C5, C7;
      section 5 `ScanStats` fields; section 6 "Stopped early" state (new text) and the early stop
      of a date-sorted search; section 8/9 config validation and error rows; AC-1, AC-15, AC-16,
      AC-19 replaced as listed in the change definition; section 11 open questions 2 and 3 resolved.
    - `features/indeed-scanner/changelog.md`: dated entry for this change.
    - `features/indeed-scanner/implementation-plan.md` (as-built) section 2 row for `scanner.py`
      (constants, functions) and section 3 config-key table (new key, meaning, default 80).
    - `architecture/security.md:30` (T-4): `scan.max_page_actions_per_run` (all page actions).
    - `architecture/data.md:88` (`config/settings.yaml` row): add "unknown keys under `scan:` and
      the removed `scan.max_new_jobs_per_run` are rejected". No other change there (it lists no
      keys).
    - `.claude/rules/indeed.md:7`: new key name and meaning.
    - `CLAUDE.md:105`: new key name and meaning. **Ask the developer before editing `CLAUDE.md`;**
      if not approved, list the exact line in the task report instead.
    - `config/searches.yaml:5` (done in step 2).
11. **Consistency check (AC-C15):** `rg max_new_jobs_per_run` finds only history (changelog, this
    change folder, `RENAMED_SETTINGS` and its test); `rg "15 jobs|RESULTS_PER_PAGE"` finds only
    history.
12. **Mistakes log.** M-004 is now guarded by tests (`test_cap_is_a_hard_limit`,
    `test_paging_constants_match_real_scan`, `test_search_url`,
    `test_paging_continues_on_full_page_and_stops_on_short_page`): delete the entry and name these
    guards in the task report (log rules). M-002: add 1 to its clean streak if every new branch got
    a test. M-001: update its clean streak if the docs were written from the built code.
13. **Hand-off:** the developer runs the manual AC-C16 check and records it for `/review-feature`.

## 8. Risks

- **R-1: An existing or newly created `config/settings.yaml` with the old key stops every command.**
  Today there is no such file (A-1). If the developer creates one from the old example before this
  ships, after this change every command that loads settings fails with the rename message until
  the line is changed. **What to rename:** under `scan:` in `config/settings.yaml`, change
  `max_new_jobs_per_run: <N>` to `max_page_actions_per_run: <M>`. Choose `M` afresh: it now counts
  result-page loads too, so `M = 80` is never more Indeed traffic than the old `80`; to keep the
  same number of descriptions per run as before, add the expected result-page loads (about
  searches x pages, 14 with the default searches). Any other unknown key under `scan:` must also be
  removed or corrected.
- **R-2: The stop signal gets swallowed.** If `_CapReached` were raised inside an
  `except Exception` (e.g. a snapshot guard), the scan would carry on past the cap. Mitigated by
  step 5's check and by AC-C6/AC-C8 tests, which would fail.
- **R-3: A future request path bypasses the counter.** Any new `goto`/`reload`/click outside
  `_load_results` / `_read_description` would not be counted. Mitigated by the single choke points,
  the `assert_counts` invariant in every scanner test, and the step 1 / review `rg` check.
- **R-4: Wrong paging constants.** A step larger than the page size silently skips jobs; a smaller
  one wastes counted actions on overlap. Mitigated by the real-scan check, the pinning test and the
  dated note. Indeed can change this later without notice.
- **R-5: Merge conflicts with `failure-screenshots` and `llm-timeout-stops-run`.** All three touch
  `cli.py`; two touch `scanner.py`. Mitigated by building this change last, on top of both (step 0,
  step 1).
- **R-6: Fake-page fidelity.** The fake page only approximates Playwright. The real flow (pane,
  `/viewjob`, blockers) is checked only by the manual AC-C16. Keep the fake minimal and typed.
- **R-7: Later searches starve.** The cap is shared and searches run in config order; counting page
  loads reaches the cap sooner, so the `remote-*` searches may get nothing on busy days. The
  date-sorted early stop reduces waste. Rotation or per-search budgets are out of scope.
- **R-8: A refused retry after a human wait can follow a counted reload.** If exactly one action is
  left after a failed first attempt and a human wait, the reload is made and the retry is refused.
  At most one such load per run; accepted for simplicity (one action is counted per check).
- **R-9: Early stop misses a job.** On a date-sorted search, a page with nothing new ends that
  search; a job posted out of order on a later page waits for the next run. Accepted (OQ-4).

## 9. Open questions and assumptions

- **OQ-1 (blocked until 2026-11-28): the values of `PAGE_STEP` and `FULL_PAGE_SIZE`**, and whether
  sponsored cards count toward a full page. Step 2 fills them in. **Approve this plan only after
  the values are recorded.**
- Assumptions A-1 to A-8 in section 1. A-3 (forbid only on `ScanSettings`) and A-5 (a missing card
  still counts) are the ones the developer may want to change.
- Out of scope, possible follow-ups (Lane C):
  - wrap `load_settings` in `login`, `decide`, `jobs` and `show` so a `ConfigError` prints a clean
    line instead of a traceback (A-4);
  - `extra="forbid"` for the other settings sections and the top level;
  - `load_searches` / `load_profile` still let a pydantic `ValidationError` through as a traceback;
  - a daily scan cap, per-search budgets, a CLI override for the cap.

## 10. ADRs needed

None. This refines an existing control (the per-run cap) and adds no new architectural choice.

Related ADRs (unchanged, checked for conflicts):
- [ADR-0001 local-only LLM](../../../../decisions/ADR-0001-local-only-llm.md): no network or LLM
  change.
- [ADR-0002 keep `src/` layout](../../../../decisions/ADR-0002-keep-src-layout.md): no new module
  outside `src/jobbot`; constants stay in `platforms/indeed/parse.py`.
- [ADR-0003 SQL migration files](../../../../decisions/ADR-0003-sql-migration-files.md): no schema
  change, so no migration.
- [ADR-0004 human approval, never auto-submit](../../../../decisions/ADR-0004-human-approval-never-auto-submit.md):
  scanning only; no submit path touched.

## 11. Safety rules (`.claude/rules/safety.md`)

| Rule | How it is kept |
|---|---|
| 1. Never auto-submit | Not touched: the scanner never fills or submits |
| 2. Everything stays local | No new network call, dependency or telemetry. Config errors are printed locally |
| 3. Protect the Indeed account | **Tightened.** The per-run cap now bounds every bot-initiated request (loads, clicks, retries, reloads), is checked before each action, and cannot be silently reset to the default by an old or misspelt key. Headed Chrome, `human_pause` and `wait_for_human` are unchanged; pauses are only skipped where no action follows. The real scan is passive observation, with checks solved by hand |
| 4. Personal data gitignored | `config/settings.yaml` was not opened (existence only). `indeed-observations.md` holds no account details; any new fixture is scrubbed first |
| 5. Never invent facts on a form | Not touched |
| 6. Untrusted input | Scraped data only feeds counts and existing parsing; no paths or commands built from it. Config error messages do not echo input values |
| 7. Approval files | This plan does not create `plan-approval.md`; implementation waits for the developer's own file |
