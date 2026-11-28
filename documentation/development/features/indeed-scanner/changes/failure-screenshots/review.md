# Review: indeed-scanner/changes/failure-screenshots

> Lane B: `features/indeed-scanner/changes/failure-screenshots/review.md`.

| | |
|---|---|
| Reviewer | AI agent |
| Date | 2026-11-28 |
| Reviewed commit / diff | `d3aafe1` (`git diff d673962..d3aafe1`, screenshots files only; `1d6f6fe` is the separate timeout change) on `docs/spec-driven-workflow` |
| Spec / request | [change-definition.md](change-definition.md) (AC-C1..AC-C16), [implementation-plan.md](implementation-plan.md), [plan-approval.md](plan-approval.md) (approved at `dba1e52`; conditions: guard built, A-8 in force) |

## 1. Summary
**Ready.** Every AC is met and backed by a test, apart from AC-C14, which was checked by hand.
There are no critical or high findings. One medium finding (F-1) is a gap that was already there
before this change. It sits next to the DOM-fallback point and is worth a small follow-up. Both
approval conditions are met: the guard (step 7) is built, and A-8 is implemented
(`run` breaks paging when `_load_results` returns `None` after a skip).

Assumptions: the review covers only the screenshots part of the range `d673962..d3aafe1`. The
real-Chrome check in plan step 9b (a page-load error against a dead URL) was not run; see F-4.

## 2. Acceptance criteria
| AC | Result | Evidence (test, command output, file:line) |
|---|---|---|
| AC-C1 naming + folder | pass | `tests/test_snapshots.py::test_snapshot_stem_format`, `::test_save_snapshot_writes_png_and_html`; `browser.py` `snapshot_stem` |
| AC-C2 key sanitising | pass | `tests/test_snapshots.py::test_sanitize_job_key` (parametrised); `browser.py` `sanitize_job_key`, plus the path-containment check in `save_snapshot` |
| AC-C3 PNG + HTML written | pass | `tests/test_snapshots.py::test_save_snapshot_writes_png_and_html` |
| AC-C4 never crashes | pass | `tests/test_snapshots.py::test_save_snapshot_failure_never_raises`, `::test_save_snapshot_lets_keyboard_interrupt_through` (catches `Exception`, not `BaseException`) |
| AC-C5 retention | pass | `tests/test_snapshots.py::test_snapshots_to_prune_keeps_newest`, `::test_prune_keeps_newest_sets_and_ignores_other_files`, `::test_prune_error_is_a_warning` |
| AC-C6 F-1 stops the scan | pass (unit) | `tests/test_indeed_scanner.py::test_goto_error_stops_scan_with_snapshot`, `::test_goto_error_without_snapshot_still_stops`; `scanner.py` `_load_results` wraps `goto` and raises `PageLoadError`. Real Chrome **not verified** (F-4) |
| AC-C7 F-1 CLI message | pass | `tests/test_cli_scan.py::test_scan_page_load_error_message`; `cli.py` `scan` catches `(HumanActionTimeout, PageLoadError)`, escapes the message, `--decide` still runs |
| AC-C8 F-2 no cards | pass | `tests/test_indeed_scanner.py::test_no_cards_on_first_page_snapshots_and_continues`, `::test_no_cards_after_full_page_is_end_of_results`, `::test_no_cards_on_retry_reload_snapshots_once` |
| AC-C9 F-3 DOM fallback once per run | pass | `tests/test_indeed_scanner.py::test_dom_fallback_snapshot_once_per_run`; `tests/test_cli_scan.py::test_scan_summary_reports_dom_fallback_and_skips` |
| AC-C10 F-4 description unreadable | pass | `tests/test_indeed_scanner.py::test_unreadable_description_snapshots_once_and_moves_on` |
| AC-C11 F-5 skip and carry on | pass | `tests/test_indeed_scanner.py::test_human_timeout_on_results_page_skips_page`, `::test_human_timeout_in_description_skips_job`; window-closed path re-raises in `_skip_after_human_timeout` |
| AC-C12 failed snapshot keeps the path | pass | `tests/test_indeed_scanner.py::test_failed_snapshot_keeps_scan_path` (F-2, F-4) |
| AC-C13 read-only snapshot | pass | `tests/test_snapshots.py::test_save_snapshot_only_reads_page`. Code review: `save_snapshot` calls only `is_closed`, `screenshot`, `content` |
| AC-C14 local and gitignored | pass (manual) | `git check-ignore -v data/screenshots/x.png` -> `.gitignore:14:data/	data/screenshots/x.png`. `browser.py` imports only `random`, `re`, `time`, `dataclasses`, `datetime`, `pathlib`, `playwright`: no network module |
| AC-C15 keep count from config | pass | `tests/test_snapshots.py::test_screenshots_keep_setting`, `::test_save_snapshot_uses_keep_count`; `config.py` `screenshots_keep: int = Field(default=50, ge=1)` |
| AC-C16 guard (2 in a row) | pass | `tests/test_indeed_scanner.py::test_two_human_timeouts_in_a_row_stop_scan`, `::test_timeout_count_resets_after_a_clear_page`; `HUMAN_TIMEOUTS_IN_A_ROW_LIMIT = 2` |

All 19 tests the plan names exist (checked by grep). The three new test files collect 43 items, and all pass.

## 3. Findings

| # | Severity | File:line | Finding | Suggested fix |
|---|---|---|---|---|
| F-1 | medium (pre-existing gap) | `src/jobbot/platforms/indeed/parse.py:49-54`, `scanner.py` `run` (`if result is None or not result.listings: break`) | If the job JSON is **present but unusable**, `parse_search_page` returns 0 listings with `source="json"`, even when the page shows `a[data-jk]` cards. Examples: `results: []`, or Indeed renaming `jobkey`. `run` then stops paging that search with no warning, no snapshot and no DOM fallback. This is exactly the "Indeed changed its page" case the change is meant to capture, but it is none of the 5 failure points (F-3 covers JSON *missing*, F-2 covers *no cards*). The behaviour already existed before this change. | Small Lane C follow-up: in `parse_search_page`, fall back to the DOM when the JSON gives 0 listings but the DOM has cards. That routes the page through the existing `dom_fallback` snapshot. Add a parse test with a JSON-empty and DOM-full fixture. |
| F-2 | low | `scanner.py` `_read_description` / `_process_page` | After a **job-level** timeout the browser is still on the check or sign-in page, so the next job finds no card link (`_click_and_read` returns `None`, with no click and no request). It then waits another `human_wait_timeout_s` and trips the guard. In practice, "skip the job and carry on" means "stop after about 2 × 300 s" while the check stays up. This is safe (no extra requests) and matches OQ-4 + OQ-5, but neither the spec nor the CLI output says so. | Document it in the spec's BR-3 / OQ-4 note. Optionally print "next job will wait again" or shorten the second wait. Behaviour change only with the developer's OK. |
| F-3 | low | `scanner.py` `_skip_after_human_timeout`; `cli.py` `scan` | The timeout that trips the guard isn't counted in `human_timeouts`. Because a stopped scan prints no summary (A-4), the counts from a stopped run are never shown. This is as designed (A-4), but it loses diagnostics. | Optional: print a short partial summary on `Scan stopped` (pages, new jobs, skips). This needs A-4 changed, so it's the developer's call. |
| F-4 | low | plan step 9b | The real-Chrome end-to-end check of a page-load error (`goto` to `http://127.0.0.1:9`) was not run. Unit tests cover the logic with a fake page, but not Playwright's real error text or a real full-page screenshot. | Run step 9b by hand once (about 2 minutes), for example during the real scan, and note the result here. |

Checked and not a finding:
- The `vjk=` / `/viewjob` markers in `scanner.py:206,221,227` were already there (open question 8 in the as-built spec). This change didn't add them.
- `_timeouts_in_a_row` is not reset per `run()`. That's harmless, because the CLI builds a new scanner for every scan (noted by the implementer).

## 4. Checklist
- [x] Safety rules hold:
  - no auto-submit, local-only, headed browser
  - no scripted login or CAPTCHA bypass: a check is never touched; every check waits for the human
  - the guard limits repeat waits
  - no form facts involved
- [x] Untrusted input handled: the scraped job key is sanitised to `[A-Za-z0-9]{0,32}` plus the path-containment check; error text is cut to its first line; the CLI escapes Rich markup and `_plain` prints with `markup=False`; no SQL changes
- [x] Schema changes are migration files (none needed: no DB change)
- [x] Prompts changed only in `llm/prompts.py` (none changed)
- [x] Indeed selectors only in `platforms/indeed/parse.py` (no new selectors; the snapshot helper in `browser.py` is platform-neutral)
- [x] No personal data or secrets in the diff (no `settings.yaml`, `profile.yaml`, `resumes/`, `data/` or `browser_profile/` paths)
- [x] Tests added and **run** (below)
- [x] `jobbot eval` not needed (no matching or prompt change)
- [x] Docs updated: the indeed-scanner spec + changelog, `architecture/data.md`, `security.md`, `overview.md`, `.claude/rules/indeed.md`, `CLAUDE.md` (with the developer's OK)
- [x] No unrelated changes (the timeout change is a separate commit, `1d6f6fe`)

## 5. Commands run
```
.venv\Scripts\python -m pytest                    -> 143 passed in 2.28s
.venv\Scripts\python -m pytest -q tests/test_snapshots.py tests/test_indeed_scanner.py tests/test_cli_scan.py -> 43 passed in 1.58s
.venv\Scripts\ruff check src tests                -> All checks passed!
.venv\Scripts\ruff format --check src tests       -> 37 files already formatted
git check-ignore -v data/screenshots/x.png        -> .gitignore:14:data/	data/screenshots/x.png
```

## 6. Remediation
Filled in by `/remediate-review`.

| # | Resolution | Notes |
|---|---|---|
| F-1 | **resolved** | The developer chose "snapshot + warn" on 2026-11-28, not a DOM fallback, because the cards may be recommendations. New reason `json_empty` in `scanner.py` (`REASON_JSON_EMPTY`, `_load_results`), with the same first-page / retry-reload rule as `no_cards`. The cards are never read. Regression tests: `tests/test_indeed_scanner.py::test_json_empty_on_first_page_snapshots_and_skips_search` (fails with the fix reverted: checked 2026-11-28) and `::test_json_empty_after_full_page_is_end_of_results`. `tests/fakes.py` `results_html` gains `json_keys`. Spec BR-13, section 9 row, AC-38; changelog; `CLAUDE.md`, `.claude/rules/indeed.md`, `architecture/data.md`. |
| F-2 | **resolved (docs)** | BR-3 in the capability spec now says that, while a check stays up, a job-level skip ends the scan after about 2 × `human_wait_timeout_s`, with no extra Indeed request in between. No code change. |
| F-3 | **deferred** | It needs assumption A-4 changed (partial summary on stop), which is the developer's call. Tracked as open question 16 in the capability spec. |
| F-4 | **deferred (developer)** | A manual real-Chrome check (plan step 9b). The developer runs it during the real scan; record the result here. |
