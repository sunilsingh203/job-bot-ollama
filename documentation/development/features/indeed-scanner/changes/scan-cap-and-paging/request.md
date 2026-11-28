# Request: scan-cap-and-paging

> Lane B (change to `indeed-scanner`; affects the pacing that protects the Indeed account).
> Drafted by Claude at the developer's request on 2026-11-27 from the as-built review. The
> developer may edit it.
> Next: `/define-feature indeed-scanner/changes/scan-cap-and-paging` → `change-definition.md`.

| | |
|---|---|
| Requested by | the developer |
| Date | 2026-11-27 |
| Related capability | `indeed-scanner` |
| Mistakes log | M-004 |

## What
Make the per-run cap and the result paging do what their config and docs say.

1. **The per-run cap.** `scan.max_new_jobs_per_run` (default 80) is documented as "stop after
   this many new jobs". `_cap_reached` (`scanner.py:138-139`) actually compares
   `stats.descriptions`, the number of descriptions read. That count also includes older rows that
   were missing a description. Search result page loads are not counted at all.
2. **Page step.** `RESULTS_PER_PAGE_STEP = 10` (`scanner.py:25`) is used both as the `start`
   offset step and as the "last page" test (`< 10` listings means stop). `config/searches.yaml`
   says "~15 jobs each" per page. One of the two is wrong, and the real page size on
   `in.indeed.com` hasn't been checked. The saved test page was cut down to 3 jobs.

## Why
The cap and the paging are what limit how much the bot does on Indeed per run, and so how risky a
run is for your account. They should count exactly what the setting's name says, and the docs
should match the code.

## Important: this is a safety trade-off, so the developer decides
- Today's counter (descriptions read) roughly equals the number of job clicks on Indeed. That
  makes it a fairly **safe** limit.
- Switching to "new jobs" could mean **more** clicks per run whenever older rows also need
  descriptions.

Options to choose between in the spec:
- **(a)** Keep counting descriptions read, and fix the name, docs and comments.
- **(b)** Count new jobs, and add a separate cap on total page loads/clicks.
- **(c)** Count every Indeed page action (result pages + description clicks) under one cap.

## Done when
- The cap counts exactly what its config name and comment say, and a unit test proves where it
  stops.
- The page step and the last-page check match how `in.indeed.com` really behaves. This needs your
  real scan (planned for 2026-11-28): note the listings per page and whether `start=10` overlaps
  with page 1.
- `config/searches.yaml`, `config/settings.example.yaml`, `config.py` and the indeed-scanner spec
  all say the same thing.

## Open questions for /define-feature
1. Option (a), (b) or (c) for the cap? Rename `max_new_jobs_per_run` if its meaning changes?
2. What does `in.indeed.com` really return: 10 or 15 cards per page, and what `start` step? This
   is blocked until your real scan.
3. Should page loads with no new jobs (all already seen) count toward a cap, and should paging
   stop early when a page has nothing new?

## Notes
- From the as-built review (2026-11-26): indeed-scanner open questions 2 and 3.

## Decisions (2026-11-27, developer in chat)
- **Open question 1: option (c).** One per-run cap counts **every Indeed page action**: each
  search-results page load plus each job-description click/read.
- The cap **replaces** `scan.max_new_jobs_per_run` under a clearer name (e.g.
  `scan.max_page_actions_per_run`).
- When the cap is reached, the scan **stops cleanly and reports** that it stopped because of the cap.
- Still open (recorded in `change-definition.md` section 7 with recommendations): the real page
  size and `start` step (blocked until the real scan on 2026-11-28), the new cap's default,
  what happens to the old key in an existing `config/settings.yaml`, early stop on a page with
  no new jobs, and whether retries/reloads after a human wait count as actions.

Later the same day (2026-11-27, developer in chat), answers to `change-definition.md` OQ-2 to OQ-5:
- **OQ-2:** the default of `scan.max_page_actions_per_run` is **80**.
- **OQ-3:** the old key `scan.max_new_jobs_per_run` is **rejected with a clear `ConfigError`**
  telling the user to rename it. `ScanSettings` gets `extra="forbid"` (so a misspelt `scan.` key
  fails too), and `load_settings` turns pydantic's `ValidationError` into a `ConfigError`.
- **OQ-4:** **stop paging a search early** when a whole page has nothing new and nothing needing a
  description, **for date-sorted searches only**.
- **OQ-5:** retries and reloads **count** as page actions. Polling while waiting for the human
  does **not**. The `go_back` after a `/viewjob` page is part of the same description read.
- **OQ-1 is still open**, blocked until the real scan on 2026-11-28 (real cards per page on
  `in.indeed.com` and the `start` step). Plan approval waits for those values.
- Related (decided in `failure-screenshots`): after a `wait_for_human` timeout the scanner skips
  the item and carries on instead of stopping. Every load, reload or click after such a skip counts
  against the cap.
