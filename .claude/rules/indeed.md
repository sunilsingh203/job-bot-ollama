# Indeed / browser rules

Details: `CLAUDE.md` "Indeed scanning", `documentation/development/architecture/security.md`.

- **Headed persistent Chrome only:** `launch_persistent_context(browser_profile/, channel="chrome", headless=False)` via `browser.open_browser`. Never headless.
- **Never script the login** or store passwords. `jobbot login` only opens the window. Check sign-in through the results JSON `loggedIn` flag.
- **Human pacing:** `human_pause` with `scan.delay_min_s`–`delay_max_s` between actions (doubled between pages). Respect `scan.max_new_jobs_per_run` and the daily fill cap (default ~25, configurable).
- **Pause on challenge / sign-in:** detect with `parse.is_challenge` / `parse.is_signin` and call `browser.wait_for_human` (timeout `browser.human_wait_timeout_s`). Never try to get past CAPTCHAs or Cloudflare automatically.
- **Selectors and markers live only in `src/jobbot/platforms/indeed/parse.py`.** `parse.py` stays pure (no browser).
- Read job descriptions the way a person does: click the card, read `#jobDescriptionText` in the right-hand pane.
- **Fail loudly:** when a page doesn't match the expected selectors, raise a clear error and save a screenshot to `data/screenshots/`. Don't guess.
- **Never click Submit.** The filler stops on the final review page (`ready_to_submit`).
- Indeed-specific code stays in `platforms/indeed/`; nothing Indeed-specific in `matcher/` or `llm/`.
- Tests use saved pages in `tests/fixtures/indeed/`, scrubbed of personal data. No test opens a browser or hits the live site.
- Record new Indeed behaviour (redirects, challenges, DOM changes) with a date in `documentation/customer/` and the `indeed-scanner` spec.
