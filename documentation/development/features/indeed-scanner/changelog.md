# Changelog: indeed-scanner

## 2026-11-26: Documented as-built
- Added `specification.md` and `implementation-plan.md`, reconstructed from the code at commit `c3677ba` (retroactive; awaiting approver review).
- Recorded the gaps against CLAUDE.md (no failure screenshots, the cap counts descriptions rather than new jobs, the page-size assumption, company size not scraped) under Open questions. No code changed.

## Initial implementation (commit c3677ba)
- Headed persistent Chrome profile (`browser.py`) with `wait_for_human` for Cloudflare checks and sign-in pages.
- Indeed parsing (`platforms/indeed/parse.py`): embedded mosaic-JSON results, DOM fallback, description pane, challenge and sign-in detection.
- Scanner (`platforms/indeed/scanner.py`): search URL building, paging, description reading by clicking cards, random pacing, per-run cap, storing jobs in the job store.
- CLI: `jobbot login`, `jobbot scan [-s NAME] [--pages N] [--decide]`.
- Tests: `tests/test_indeed_parse.py` with the trimmed real results page fixture.
