# Changelog: indeed-scanner

## 2026-11-28: Review remediation (`changes/failure-screenshots/review.md`)
- **F-1:** a sixth failure point, `json_empty`. When a search's first page (or the description-retry reload) shows cards but the job JSON lists no jobs, the scanner warns, saves a snapshot and skips that search's paging. It never reads those cards (developer decision 2026-11-28: they may be "jobs you may like", not results). AC-38.
- **F-2:** BR-3 documents that, while a check stays up, a job-level skip ends the scan after about 2 × `human_wait_timeout_s` (no behaviour change).
- **F-3** (partial summary on stop) deferred as open question 16. **F-4** (real-Chrome check of a page-load error) left to the developer.

## 2026-11-28: Failure screenshots (`changes/failure-screenshots`)
- At five failure points the scanner saves a local snapshot (PNG + page HTML) to `data/screenshots/` and prints the path: `goto_error`, `no_cards` (first page of a search or the description-retry reload only), `dom_fallback` (once per run, plus a summary line), `no_description_<jobkey>` (once per job), `human_timeout`. Newest `browser.screenshots_keep` (default 50) sets kept. Writing a snapshot never navigates and never crashes the scan (`browser.save_snapshot`).
- A results-page `goto` error now stops the scan cleanly (`Scan stopped: page load failed: ... Screenshot: ... (progress is saved)`, exit 0, `--decide` still runs) instead of a traceback (`PageLoadError`).
- **Behaviour change (developer decision OQ-4, 2026-11-27):** a check/sign-in timeout now **skips** the page (that search's paging ends, A-8) or the job and carries on, instead of stopping the scan. Guard (OQ-5): 2 timeouts in a row stop the scan. A closed window still stops it. The summary gains `Skipped after an unsolved check/sign-in: N`.
- New config key `browser.screenshots_keep`. No DB change.
- Spec: BR-3 amended; BR-13, BR-14 and AC-22..AC-37 added; AC-9, AC-10, AC-20, AC-21 updated; Open question 1 resolved.
- Tests: `tests/fakes.py` (fake page), `tests/test_snapshots.py`, `tests/test_indeed_scanner.py` (the first scanner-loop tests), `tests/test_cli_scan.py`.

## 2026-11-26: Documented as-built
- Added `specification.md` and `implementation-plan.md`, reconstructed from the code at commit `c3677ba` (retroactive; awaiting approver review).
- Recorded the gaps against CLAUDE.md (no failure screenshots, the cap counts descriptions rather than new jobs, the page-size assumption, company size not scraped) under Open questions. No code changed.

## Initial implementation (commit c3677ba)
- Headed persistent Chrome profile (`browser.py`) with `wait_for_human` for Cloudflare checks and sign-in pages.
- Indeed parsing (`platforms/indeed/parse.py`): embedded mosaic-JSON results, DOM fallback, description pane, challenge and sign-in detection.
- Scanner (`platforms/indeed/scanner.py`): search URL building, paging, description reading by clicking cards, random pacing, per-run cap, storing jobs in the job store.
- CLI: `jobbot login`, `jobbot scan [-s NAME] [--pages N] [--decide]`.
- Tests: `tests/test_indeed_parse.py` with the trimmed real results page fixture.
