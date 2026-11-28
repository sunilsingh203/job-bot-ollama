# Indeed / browser rules

Details: `CLAUDE.md` "Indeed scanning", `documentation/development/architecture/security.md`.

- **Headed persistent Chrome only:** `launch_persistent_context(browser_profile/, channel="chrome", headless=False)` via `browser.open_browser`. Never headless.
- **Never script the login** or store passwords. `jobbot login` only opens the window. Check sign-in through the results JSON `loggedIn` flag.
- **Human pacing:** `human_pause` with `scan.delay_min_s`–`delay_max_s` between actions (doubled between pages). Respect `scan.max_new_jobs_per_run` and the daily fill cap (default ~25, configurable).
- **Pause on challenge / sign-in:** detect with `parse.is_challenge` / `parse.is_signin` and call `browser.wait_for_human` (timeout `browser.human_wait_timeout_s`). Never try to get past CAPTCHAs or Cloudflare automatically. In the scanner a timeout skips that page or job (developer decision 2026-11-27); a closed window or 2 timeouts in a row (`HUMAN_TIMEOUTS_IN_A_ROW_LIMIT`) stop the scan. Keep that guard.
- **Selectors and markers live only in `src/jobbot/platforms/indeed/parse.py`.** `parse.py` stays pure (no browser).
- Read job descriptions the way a person does: click the card, read `#jobDescriptionText` in the right-hand pane.
- **Fail loudly:** when a page doesn't match what's expected, save a snapshot with `browser.save_snapshot` (PNG + HTML to `data/screenshots/`, newest `browser.screenshots_keep` kept, read-only, never raises) and print the path. Don't guess. The scanner does this at 6 points (`goto_error` stops the scan; `no_cards`, `dom_fallback`, `json_empty`, `no_description`, `human_timeout` skip or carry on). Never read cards whose job JSON lists no jobs (`json_empty`). Snapshots can hold the signed-in name/email: scrub before any reuse as a fixture.
- **Never click Submit.** The filler stops on the final review page (`ready_to_submit`).
- Indeed-specific code stays in `platforms/indeed/`; nothing Indeed-specific in `matcher/` or `llm/`.
- Tests use saved pages in `tests/fixtures/indeed/`, scrubbed of personal data. No test opens a browser or hits the live site.
- Record new Indeed behaviour (redirects, challenges, DOM changes) with a date in `documentation/customer/` and the `indeed-scanner` spec.
