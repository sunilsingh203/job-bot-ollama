# Specification: indeed-scanner

Status: As-built — documented retroactively on 2026-11-26 from the existing code. Awaiting review by the approver (approval: by the developer, by hand or recorded from chat — ADR-0005).

Capability: scan Indeed India search results in a visible, human-supervised Chrome window,
store every listing in the job store, and read each job's full description.
Pipeline position: `SCAN` (this capability) -> `FILTER` / `DECIDE` (resume-matcher, via job-store).

All file:line references are to commit `c3677ba`, except where a rule was added or changed by
[`changes/failure-screenshots`](changes/failure-screenshots/change-definition.md) (built 2026-11-28);
those rows name the function instead.

---

## 1. Purpose

Finding jobs by hand on Indeed is slow. This capability runs the user's saved searches
(keyword x location) on `in.indeed.com`, collects the result listings (title, company,
location, "Easily apply" flag, salary, posting date, snippet), and reads each job's full
description the way a person would: by clicking the card and reading the right-hand pane.
Everything is written to the local SQLite job store, so that the LLM decision step
(`jobbot decide`) can run later, separately and offline from the browser.

The scanner must protect the user's Indeed account. It runs slowly, in a visible window,
with the user's own manually signed-in session. It never automates past a CAPTCHA,
Cloudflare check or sign-in page.

## 2. Actors

| Actor | Role |
|---|---|
| Developer / operator (the single local user) | Edits `config/searches.yaml` and `config/settings.yaml`, runs `jobbot login` and `jobbot scan`, signs in to Indeed by hand, and solves any "Verify you are human" check in the visible window. |
| The bot (`jobbot` CLI + `IndeedScanner`) | Opens the persistent Chrome profile, loads search pages, parses listings, clicks cards, reads descriptions, writes to the job store, and pauses for the human when blocked. |
| Indeed (`in.indeed.com`, `secure.indeed.com`) | External system. Serves search pages (with embedded JSON), job panes and `/viewjob` pages. It may redirect to sign-in. |
| Cloudflare (in front of Indeed) | External system. May show "Just a moment..." / "Additional Verification Required" / "Verify you are human" challenges after a few automated page loads (observed 2026-11-21). |
| Job store (`job-store` capability) | Persists listings and descriptions and detects duplicates. |
| Local LLM (Ollama) | Not used by the scanner. It is only involved when `jobbot scan --decide` hands over to the job-store/resume-matcher decide step after scanning. |

## 3. Scope

In scope:
- Building Indeed search URLs from `config/searches.yaml` (query, location, sort, `fromage`, page offset, raw extra params).
- Loading result pages in a headed, persistent Chrome profile (Playwright, `channel="chrome"`).
- Parsing listings from the embedded `mosaic-provider-jobcards` JSON, with a DOM fallback.
- Upserting each listing into the job store (dedup by platform + job key).
- Reading the full job description for every stored job that has none yet (side pane, or a full `/viewjob` page as a fallback).
- Detecting Cloudflare challenges and sign-in pages, and waiting for the human to resolve them (with a timeout).
- Random, human-like pacing and a per-run cap on descriptions read.
- `jobbot login`: open the profile so the user can sign in by hand once, and check the sign-in state through Indeed's own `loggedIn` flag.
- `jobbot scan` CLI options: `--search/-s` (subset of searches), `--pages` (override `max_pages`), `--decide` (run the decide step afterwards).
- Saving a local failure snapshot (PNG + HTML) to `data/screenshots/` at six failure points (BR-13).

Out of scope (not implemented, or owned by other capabilities):
- Rule filtering and the LLM apply/skip decision (resume-matcher; started from job-store `decide_pending`).
- Reading company size from Indeed company pages. The `company_size` column exists but the scanner never fills it (see Open questions).
- Applying / form filling (planned Step 4) and the review dashboard (planned Step 3).
- Platforms other than Indeed India.
- Any automated login, credential storage, CAPTCHA solving or challenge bypass. These are forbidden, not just out of scope.
- Headless operation (forbidden).
- Snapshots in `jobbot login` (A-6 of `failure-screenshots`), and snapshots for unexpected Playwright errors outside the six failure points (these still end in a traceback; see Open questions).

## 4. Business rules

| ID | Rule | Where |
|---|---|---|
| BR-1 | The browser is always headed (`headless=False`) and uses a dedicated persistent profile directory (`browser.profile_dir`, default `browser_profile/`). | `src/jobbot/browser.py:35-40`, `src/jobbot/config.py:57-62` |
| BR-2 | The bot never types credentials or scripts a login. `jobbot login` only opens the sign-in page and waits for the user. | `src/jobbot/cli.py:261-307` |
| BR-3 | When a Cloudflare challenge or a sign-in page is detected, the bot stops acting, prints a message, brings the window to the front, and polls every 2 s until the user resolves it, for up to `browser.human_wait_timeout_s` (default 300 s). **On a timeout** (changed 2026-11-27 by the developer's decision OQ-4 of `failure-screenshots`; before, every timeout stopped the scan): a `human_timeout` snapshot is saved, `! still blocked after Ns - skipped this page` (or `job`) is printed, and the item is skipped. On a results page, that search's paging stops and the scan moves to the next search (A-8). In the description reader, that job is skipped (NULL description, retried next scan). The bot never interacts with the check, and every later check waits for the human again. **Stops instead:** if the window was closed (no snapshot), or on the 2nd timeout in a row (BR-14). **In practice** (review F-2, 2026-11-28): after a job-level timeout the window still shows the check, so the next job finds no card (no click, no request), waits again and trips the guard. While a check stays up, a job-level skip therefore ends the scan after about 2 × `human_wait_timeout_s`. | `browser.wait_for_human`, `scanner._check_blockers`, `scanner._skip_after_human_timeout` |
| BR-4 | Search results are parsed from the embedded JSON `window.mosaic.providerData["mosaic-provider-jobcards"]` -> `metaData.mosaicProviderJobCardsModel.results[]`. If the JSON is missing, has no `results` list or cannot be decoded, the DOM fallback (`a[data-jk]` cards) is used. | `parse.py:49-54`, `parse.py:79-90` |
| BR-5 | A job's identity is `(platform="indeed", job_key=jk)`. Listings are de-duplicated within a page by job key and across runs by the job store's unique key. | `parse.py:144-151`, `db.py:49` |
| BR-6 | A description is fetched only for stored jobs whose `description` is NULL (`needs_description`). Jobs seen again in a later scan are not re-read. | `scanner.py:117`, `db.py:204-206` |
| BR-7 | Pacing: a random 1.0–2.5 s pause after each results page loads; 0.4–1.2 s before clicking a card; `scan.delay_min_s`–`scan.delay_max_s` (default 2.5–6.0 s) after each description attempt; twice that range between result pages. | `scanner.py:84, 99, 135, 166` |
| BR-8 | Per-run cap: once `scan.max_new_jobs_per_run` (default 80) descriptions have been read in this run, no further descriptions are read and no further pages are loaded. Note: the cap counts **descriptions read**, not new jobs (see Open questions). | `scanner.py:68-72, 119-120, 138-139` |
| BR-9 | Paging: pages are requested with `start = page_index * 10`. Paging for a search stops when a page has no results, or fewer than 10 listings (treated as the last page), or `max_pages` is reached. | `scanner.py:25, 42-49, 76-83` |
| BR-10 | All Indeed selectors and text markers live in `platforms/indeed/parse.py` (with the exceptions noted in Open questions). | `parse.py:21-32` |
| BR-11 | Scan and decide are separate steps. Scanning never needs the LLM; `--decide` simply runs the decide step after the browser has closed. | `cli.py:330-354` |
| BR-12 | Progress is durable: every upsert and description write is committed immediately, so an interrupted scan (timeout, Ctrl+C) keeps what it stored. | `db.py` (commit after each write), `cli.py:336-341` |
| BR-13 | **Failure snapshots.** At six failure points the scanner saves `data/screenshots/<YYYYMMDD-HHMMSS-mmm>_<reason>[_<jobkey>].png` and `.html` (local time; full-page PNG with a 10 s timeout; HTML as UTF-8) and prints `screenshot: <path> (+ .html)`. Reasons: `goto_error` (results page failed to load: **the scan stops**), `no_cards` (only on a search's first page, or on the results reload inside the description retry; a later empty page is the end of results), `dom_fallback` (once per run; the summary gains a line), `json_empty` (the job JSON lists no jobs although cards are shown: `! job JSON lists no jobs although cards are shown - skipped this page`; same first-page / retry-reload rule as `no_cards`; the cards are **not** read, because they may be recommendations rather than results, and that search's paging stops; added 2026-11-28, review F-1), `no_description` (once per job, after both attempts; key part = the sanitised job key, `[A-Za-z0-9]` only, at most 32 chars), `human_timeout` (BR-3). The snapshot only reads the page (`is_closed`, `screenshot`, `content`), never navigates or clicks, and never raises: any error becomes one `! could not save screenshot: ...` line and the scan carries on as if it had worked. After each save only the newest `browser.screenshots_keep` (default 50, min 1) sets are kept; other files in the folder are left alone. | `browser.save_snapshot`, `browser.prune_snapshots`, `scanner._snapshot` |
| BR-14 | **Guard:** `HUMAN_TIMEOUTS_IN_A_ROW_LIMIT = 2` human-wait timeouts in a row (no blocker check passed and no description was read in between) stop the scan with `HumanActionTimeout` after the snapshot, to protect the account (OQ-5, accepted 2026-11-27). | `scanner._skip_after_human_timeout`, `scanner._handle_blockers` |

## 5. Data entities

The scanner persists nothing outside the job store (and the Chrome profile managed by Chrome),
except failure snapshots in `data/screenshots/` (BR-13).

| Entity | Fields | Notes |
|---|---|---|
| `Search` (config, `config/searches.yaml`) | `name` (unique), `query`, `location` (default `India`), `max_pages` (default 2), `fromage` (default 3; `null`/0 = omitted), `sort` (default `date`), `extra_params` (raw Indeed URL params) | Defaults under the `defaults:` key are merged into each search. `src/jobbot/config.py:82-104` |
| `Listing` (in memory) | `job: Job`, `snippet: str | None`, `sponsored: bool` | `sponsored` is parsed but never stored or used. `parse.py:35-39` |
| `SearchPage` (in memory) | `listings`, `logged_in: bool | None`, `source: "json" | "dom"` | `logged_in` is only known on the JSON path. `parse.py:42-46` |
| `Job` fields set by the scanner | `title`, `company`, `location`, `url` (`{base}/viewjob?jk={jk}`), `platform="indeed"`, `job_key`, `easy_apply`, `remote`, `salary`, `posted_at` (ISO date, UTC), `description` (later) | `src/jobbot/models.py:11-27`; see field mapping below |
| `ScanStats` (in memory, printed) | `pages`, `listings_seen`, `new_jobs`, `descriptions`, `description_failures`, `duplicates`, `logged_in`, `per_search`, `stopped_early`, `dom_fallback_pages`, `dom_fallback_snapshot`, `human_timeouts` | `scanner.ScanStats` |
| Failure snapshot set (`data/screenshots/`) | `<stem>.png` + `<stem>.html`, stem `<YYYYMMDD-HHMMSS-mmm>_<reason>[_<jobkey>]` | Local and gitignored; newest `browser.screenshots_keep` sets kept. The HTML (and PNG) can hold the signed-in name/email and session tokens: never share or turn into a fixture without scrubbing. `browser.Snapshot` describes what was written. |
| Job row | See the job-store specification. | `db.py` |

Field mapping, JSON path (`parse.py:93-115`):

| Job field | Mosaic JSON source |
|---|---|
| `job_key` | `jobkey` |
| `title` | `displayTitle`, else `title` |
| `company` | `company`, else `truncatedCompany` |
| `location` | `formattedLocation` |
| `easy_apply` | `indeedApplyEnabled` or `indeedApplyable` |
| `remote` | `remoteLocation` (truthy) |
| `salary` | `salarySnippet.text` |
| `posted_at` | `pubDate` (ms epoch) -> UTC date, ISO `YYYY-MM-DD`; only if > 0 |
| snippet | `snippet` HTML -> plain text |
| (sponsored) | `sponsored` |
| (page) `logged_in` | `mosaicProviderJobCardsModel.loggedIn` |

DOM fallback (`parse.py:118-141`): `title` = anchor text; `company` = `[data-testid='company-name']`;
`location` = `[data-testid='text-location']`; `easy_apply` = card text contains "easily apply";
`remote` = location text contains "remote". No salary, posting date, snippet or sponsored flag.
The card scope is the closest `.job_seen_beacon`, else the closest `li`, else the anchor itself.

## 6. States and transitions

Scanner-driven job-row transitions (the full lifecycle lives in the job-store specification):

| From | Event | To | Where |
|---|---|---|---|
| (no row) | Listing seen for the first time | `new` (description NULL) | `db.upsert_listing` |
| any status | Listing seen again | unchanged (only `easy_apply`, `salary`, `updated_at` refreshed) | `db.upsert_listing` |
| `new` (description NULL) | Description read; no other row has the same description hash | `new` (description set) | `db.set_description` |
| `new` (description NULL) | Description read; another row has an identical description hash | `duplicate` (error = "Same description as job #N") | `db.set_description` |
| `new` (description NULL) | Description could not be read | unchanged (retried on the next scan) | `scanner.py:132-134` |

Scan-run states (in memory):

| State | Trigger | Next |
|---|---|---|
| Loading results page | `goto(search_url)` | Blocked / Parsing / No results / Stopped by page-load error |
| Stopped by page-load error | `goto` raised | `goto_error` snapshot; `PageLoadError` -> `Scan stopped: page load failed: ... Screenshot: ...`; progress kept |
| Blocked (challenge or sign-in) | `is_challenge` / `is_signin` true | Waiting for human |
| Waiting for human | user resolves it | resume previous action |
| Waiting for human | timeout | `human_timeout` snapshot; item skipped (page: next search; job: next job) |
| Waiting for human | window closed, or 2nd timeout in a row (BR-14) | Scan stopped (`HumanActionTimeout`); progress kept |
| Parsing / reading descriptions | — | next card / next page / next search |
| Stopped early | description cap reached | summary printed with `Stopped early: reached max_new_jobs_per_run=N` |
| Done | all searches processed | summary printed; optional decide step |

## 7. Permissions & data scope

- Single local user. There is no authentication or authorization inside jobbot; whoever can run the CLI on this machine owns all data.
- All data stays local: `data/jobs.db`, `browser_profile/` (Chrome session cookies) and config files. The scanner makes no network calls except to Indeed through the visible browser. No telemetry, no cloud APIs.
- `browser_profile/` and `data/` are gitignored (`.gitignore`). The profile holds the Indeed session and must never be committed or shared.
- Indeed account protection:
  - The user signs in by hand; jobbot never sees or stores a password (`cli.py:289-294`).
  - Never headless; never bypass CAPTCHA or Cloudflare. The bot only waits.
  - Slow, randomised pacing and a per-run description cap limit request volume.
  - Only one browser per profile: a second concurrent launch fails with a `BrowserError` hint (`browser.py:41-45`).

## 8. Validation rules

| ID | Rule | Where |
|---|---|---|
| V-1 | `config/searches.yaml` must exist, contain at least one search, and have unique search names; otherwise `ConfigError` with a fix hint. | `config.py:92-104` |
| V-2 | Each search is validated by the pydantic `Search` model (`name` and `query` required). | `config.py:82-89` |
| V-3 | `jobbot scan --search NAME` with an unknown name fails with `Unknown search name(s): ...` (exit 1). | `cli.py:324-328` |
| V-4 | A JSON result without `jobkey` is skipped; a DOM anchor without `data-jk` is skipped. | `parse.py:52, 122-124` |
| V-5 | A description is stored only if non-empty text was read. | `scanner.py:123` |
| V-6 | A pane description is accepted only if the URL contains `vjk={jk}` and the pane text differs from the text before the click (unless that card was already open). | `scanner.py:179-181` |
| V-7 | `settings.yaml` values are validated by pydantic (`BrowserSettings`, `ScanSettings`); relative `profile_dir` is resolved against the project root. | `config.py:57-70, 131-144` |

## 9. Error cases

| Case | Behaviour | Where |
|---|---|---|
| Chrome cannot start (profile locked by another window, Chrome missing) | `BrowserError` -> `Error: Could not start Chrome ... Is another jobbot window still open?` exit 1 | `browser.py:41-45`, `cli.py:338-339` |
| Cloudflare challenge / sign-in redirect | Pause and wait for the human (BR-3) | `scanner.py:203-222` |
| Human does not resolve within `human_wait_timeout_s` | `human_timeout` snapshot, `! still blocked after Ns - skipped this page` (or `job`), item skipped (BR-3); the summary gains `Skipped after an unsolved check/sign-in: N`. The 2nd in a row stops the scan: `Scan stopped: 2 checks/sign-ins in a row were not solved; stopping the scan to protect the Indeed account. Screenshot: <path> (progress is saved)` (BR-14) | `scanner._skip_after_human_timeout`, `cli.scan` |
| User closes the browser window while waiting | No snapshot; scan stops: `Scan stopped: The browser window was closed. Screenshot: none (window closed) (progress is saved)` | `browser.wait_for_human`, `scanner._skip_after_human_timeout` |
| Ctrl+C | `Scan interrupted (progress is saved).` (a snapshot in progress does not swallow Ctrl+C) | `cli.py:340-341` |
| Results page shows no cards within 20 s | `no results on this page`; this search's paging stops. `no_cards` snapshot only on a search's first page or the description-retry reload | `scanner._load_results` |
| Mosaic JSON missing or undecodable | DOM fallback (`source="dom"`, `logged_in=None`); on the first such page of a run: `job JSON missing - reading cards from the page (DOM fallback)` + `dom_fallback` snapshot; summary: `DOM fallback used on N pages (job JSON missing). Screenshot: <path>` | `parse.py:49-54, 79-90`, `scanner._note_dom_fallback` |
| Description not read (timeout 15 s, card missing, blocked, Playwright error) | One retry (after reloading results if the bot had to wait for the human); then counted in `description_failures`, `! no description: ...` printed, one `no_description_<jobkey>` snapshot; job keeps a NULL description and is retried on the next scan. A job given up because of a human-wait timeout or an empty reload gets only that snapshot | `scanner._read_description` |
| Card opens as a full `/viewjob` page | Description parsed from that page, then `go_back` to results | `scanner.py:174-178` |
| `page.goto` of a results page fails (network error, timeout, Chrome error page), also on the description-retry reload | `goto_error` snapshot, then the scan **stops**: `Scan stopped: page load failed: <first line>. Screenshot: <path> (progress is saved)`, exit 0, no traceback; `--decide` still runs | `scanner._load_results`, `browser.PageLoadError`, `cli.scan` |
| A snapshot can't be written (screenshot/HTML/folder/prune error) | One `! could not save screenshot: ...` (or `! could not delete old screenshot ...`) line; the scan takes the same path as if it had worked | `browser.save_snapshot` |
| Other unexpected Playwright errors (e.g. a non-timeout error from `wait_for_selector`, or `page.content()` failing while parsing) | Not caught: traceback, no snapshot (A-7 / R-6 of `failure-screenshots`). Committed rows are kept. | `scanner._load_results` |
| Job JSON present but lists no jobs while cards are shown | On a search's first page or the description-retry reload: `! job JSON lists no jobs although cards are shown - skipped this page` and a `json_empty` snapshot; the cards are not read; that search's paging stops. On a later page: treated as the end of results (no warning, no snapshot). | `scanner._load_results` |
| Indeed DOM/JSON changes | Falls back to DOM (snapshot once per run); if that also fails, pages yield "no results" or description failures, each with a snapshot as above. | — |

## 10. Acceptance criteria (current behaviour)

**AC-1: Search URL.** `search_url(base, search, page_index)` returns `{base}/jobs?` with `q`, `l`, `sort` and `fromage` (only when `fromage` is truthy), `start = page_index * 10` (only when `page_index > 0`), then `extra_params` URL-encoded, in that order.
Verified by: tests/test_indeed_parse.py::test_search_url

**AC-2: Searches config.** `load_searches` merges `defaults` into each search, and raises `ConfigError` when the file is missing, has no searches, or has duplicate names.
Gap: no automated test (manual: delete or duplicate a search name in a copy of `config/searches.yaml` and run `jobbot scan`; expect a clear error, exit 1).

**AC-3: JSON parsing.** For a page that contains the mosaic job-cards JSON, `parse_search_page` returns `source="json"`, `logged_in` from `loggedIn`, and one listing per result with a `jobkey`, with the fields mapped as in the section 5 table (`url = {base}/viewjob?jk={jk}`, `platform="indeed"`, ISO `posted_at`, salary text, `easy_apply` from `indeedApplyEnabled`).
Verified by: tests/test_indeed_parse.py::test_parse_real_search_page_json

**AC-4: Snippet to text.** The HTML `snippet` is converted to plain text (no tags left).
Verified by: tests/test_indeed_parse.py::test_parse_real_search_page_json

**AC-5: DOM fallback.** When the mosaic JSON is absent or not valid JSON, listings are parsed from `a[data-jk]` cards with `source="dom"`: title, company, location, `easy_apply` from the "Easily apply" text, and `remote` from the location text.
Verified by: tests/test_indeed_parse.py::test_dom_fallback_when_json_missing, tests/test_indeed_parse.py::test_broken_json_falls_back_to_dom

**AC-6: In-page dedup.** Listings with the same job key on one page appear once, in first-seen order.
Verified by: tests/test_indeed_parse.py::test_dom_fallback_when_json_missing (DOM path only; the JSON path dedup is not tested).

**AC-7: Description parsing.** `parse_description` returns the text of `#jobDescriptionText` with list items as `- ` lines, or `None` when the element is missing.
Verified by: tests/test_indeed_parse.py::test_parse_description

**AC-8: Blocker detection.** `is_challenge` is true when the title contains "just a moment", or the first 60,000 characters of the HTML contain "additional verification required" or "verify you are human" (case-insensitive). `is_signin` is true when the URL contains `secure.indeed.com/auth`, `secure.indeed.com/account/login` or `/account/login`.
Verified by: tests/test_indeed_parse.py::test_challenge_and_signin_detection

**AC-9: Wait for human.** When a blocker is detected, the bot prints the instruction, brings the window to the front, polls every 2 s, continues with "Thanks - continuing." once it clears, and raises `HumanActionTimeout` after `browser.human_wait_timeout_s`, or immediately when the window is closed. Playwright errors during the check count as "still blocked". In the scanner, what follows a timeout is AC-32 (skip) and AC-37 (guard).
Verified by (scanner use, with a fake page): tests/test_indeed_scanner.py::test_no_cards_on_retry_reload_snapshots_once (waits, then "Thanks - continuing."), ::test_human_timeout_on_results_page_skips_page, ::test_human_timeout_window_closed_stops_scan. Gap: the 2 s polling interval against a live check (manual: run `jobbot scan` until a Cloudflare check appears).

**AC-10: Never automates past blockers.** No code path clicks, types into or otherwise interacts with a challenge or sign-in page; the only action while blocked is polling the page state.
Verified by: tests/test_indeed_scanner.py::test_human_timeout_on_results_page_skips_page (only `title`/`content`/`is_closed`/`bring_to_front`/`screenshot` while blocked); plus code review of `browser.wait_for_human` and `scanner._handle_blockers`.

**AC-11: Cross-run dedup.** A listing whose `(platform, job_key)` already exists is not inserted again and does not count as new; its description is fetched only if still NULL.
Verified by: tests/test_db_pipeline.py::test_upsert_is_idempotent (store level). Gap: the scanner loop itself has no automated test (manual: run the same search twice; the second run reports `0 new jobs` for unchanged results).

**AC-12: Description reading.** For each stored job that needs a description, the bot scrolls to and clicks its card, waits up to 15 s for the side pane (`#jobDescriptionText`) to show new text with `vjk={jk}` in the URL (or reads a full `/viewjob` page and goes back), stores the text, and prints `+ title @ company [easy apply]`. On failure it retries once, then prints `! no description: ...` and leaves the description NULL.
Gap: no automated test (manual: `jobbot scan -s <name> --pages 1`, then `jobbot show ID` shows the full description).

**AC-13: Duplicate descriptions.** If the read description is identical to another stored job's description, the job becomes `duplicate` and the scan line ends with `(duplicate)`.
Verified by: tests/test_db_pipeline.py::test_duplicate_descriptions (store level).

**AC-14: Pacing.** Random pauses as in BR-7 are applied (between pages: `2*delay_min_s`–`2*delay_max_s`).
Gap: no automated test (manual: observe the timing in the visible window, or review the code).

**AC-15: Per-run cap.** When the number of descriptions read in this run reaches `scan.max_new_jobs_per_run`, the scan stops reading descriptions and loading pages, and the summary prints `Stopped early: reached max_new_jobs_per_run=N`.
Gap: no automated test (manual: set `max_new_jobs_per_run: 2` in `config/settings.yaml` and run a scan).

**AC-16: Paging stop.** For each search, at most `--pages` (if given) or `max_pages` pages are loaded; paging stops early when a page has no cards within 20 s or fewer than 10 listings.
Gap: no automated test (manual: a narrow search with few results loads only 1 page).

**AC-17: Browser profile.** `open_browser` launches installed Chrome (`browser.channel`) headed, with a persistent context in `browser.profile_dir` (created if missing) and a 1366x900 viewport. A launch failure raises `BrowserError` with the "Is another jobbot window still open?" hint.
Gap: no automated test (manual: run `jobbot scan` while `jobbot login` is still open; expect the error).

**AC-18: Login.** `jobbot login [--timeout-min 10]` loads the first configured search (waiting for any challenge) and reads `loggedIn` from the results JSON. If true it prints "Already signed in to Indeed." Otherwise it opens `{base}/account/login`, waits (up to the timeout) while the URL is a sign-in URL or off the Indeed base, re-checks `loggedIn`, and prints "Signed in. The session is saved in browser_profile/." or fails with "Indeed still reports you as signed out." (exit 1). No credentials are ever typed by the bot.
Gap: no automated test (manual: run `jobbot login` with a fresh profile, sign in by hand, run it again and expect "Already signed in").

**AC-19: Scan CLI.** `jobbot scan [-s NAME ...] [--pages N] [--decide]` runs only the named searches (unknown names: error, exit 1), overrides `max_pages` with `--pages`, and prints `Scan done: P pages, L listings, N new jobs, D descriptions read, F failed, U duplicates | signed in: yes|no|unknown`. `signed in` reflects the last page that was loaded.
Gap: no automated test (manual run).

**AC-20: Stopped scans keep progress.** When the scan stops (page-load error AC-28, window closed AC-32, guard AC-37) or on Ctrl+C, the CLI prints a "progress is saved" message (exit 0), and all listings and descriptions stored before that point remain in `data/jobs.db`. A single check/sign-in timeout no longer stops the scan (AC-32).
Verified by: tests/test_indeed_scanner.py::test_goto_error_stops_scan_with_snapshot[later] (rows kept); tests/test_cli_scan.py (messages, exit 0). Gap: Ctrl+C (manual: Ctrl+C mid-scan, then `jobbot jobs`).

**AC-21: Scan then decide.** With `--decide`, the decide step (job-store `decide_pending`) runs after the browser closes, also when the scan stopped (AC-20) or ended through Ctrl+C.
Verified by: tests/test_cli_scan.py::test_scan_page_load_error_message, ::test_scan_window_closed_message (`_run_decide` patched). Gap: Ctrl+C and a real decide run (manual: `jobbot scan --decide` with Ollama running).

### Added by `failure-screenshots` (2026-11-28; AC-C1..AC-C16 of the change definition)

**AC-22 (AC-C1): Snapshot naming.** The stem is `<YYYYMMDD-HHMMSS-mmm>_<reason>[_<jobkey>]`; files `<stem>.png` and `<stem>.html` in `<data_dir>/screenshots/`, created if missing.
Verified by: tests/test_snapshots.py::test_snapshot_stem_format, ::test_save_snapshot_writes_png_and_html

**AC-23 (AC-C2): Job key sanitising.** Only `[A-Za-z0-9]`, at most 32 characters, no key part when nothing is left; the path stays inside the folder.
Verified by: tests/test_snapshots.py::test_sanitize_job_key

**AC-24 (AC-C3): PNG and HTML written,** HTML as UTF-8, one `screenshot:` line with the path.
Verified by: tests/test_snapshots.py::test_save_snapshot_writes_png_and_html

**AC-25 (AC-C4): A snapshot failure never crashes.** Screenshot, HTML or folder errors give one `! could not save screenshot` line (first line of the error only); the other file is still written. Ctrl+C is not swallowed.
Verified by: tests/test_snapshots.py::test_save_snapshot_failure_never_raises, ::test_save_snapshot_lets_keyboard_interrupt_through

**AC-26 (AC-C5): Retention.** The newest `browser.screenshots_keep` sets are kept (by name timestamp); other files are left alone; a delete error is a warning.
Verified by: tests/test_snapshots.py::test_snapshots_to_prune_keeps_newest, ::test_prune_keeps_newest_sets_and_ignores_other_files, ::test_prune_error_is_a_warning

**AC-27 (AC-C15): Keep count from config.** `browser.screenshots_keep`, default 50, below 1 rejected.
Verified by: tests/test_snapshots.py::test_screenshots_keep_setting, ::test_save_snapshot_uses_keep_count

**AC-28 (AC-C6, AC-C7): Page-load error stops the scan.** A `goto` error saves `goto_error`, loads and clicks nothing more, and raises `PageLoadError` (with the snapshot, or `not saved`); the CLI prints `Scan stopped: page load failed: <first line>. Screenshot: <path> (progress is saved)`, no traceback, and `--decide` still runs.
Verified by: tests/test_indeed_scanner.py::test_goto_error_stops_scan_with_snapshot, ::test_goto_error_without_snapshot_still_stops; tests/test_cli_scan.py::test_scan_page_load_error_message

**AC-29 (AC-C8): No cards.** `no_cards` only on a search's first page or the description-retry reload (that job is then given up with no other snapshot); a later empty page saves nothing; the scan goes on with the next search.
Verified by: tests/test_indeed_scanner.py::test_no_cards_on_first_page_snapshots_and_continues, ::test_no_cards_after_full_page_is_end_of_results, ::test_no_cards_on_retry_reload_snapshots_once

**AC-30 (AC-C9): DOM fallback.** Listings are processed as before; one `dom_fallback` snapshot per run; the summary prints `DOM fallback used on N pages (job JSON missing). Screenshot: <path>`.
Verified by: tests/test_indeed_scanner.py::test_dom_fallback_snapshot_once_per_run; tests/test_cli_scan.py::test_scan_summary_reports_dom_fallback_and_skips, ::test_scan_summary_dom_fallback_without_snapshot

**AC-31 (AC-C10): Unreadable description.** Exactly one `no_description_<jobkey>` set per job, NULL description, `description_failures` +1, next job read.
Verified by: tests/test_indeed_scanner.py::test_unreadable_description_snapshots_once_and_moves_on

**AC-32 (AC-C11): Check/sign-in timeout skips the item.** `human_timeout` snapshot and `! still blocked after Ns - skipped this page` (or `job`); results page: next search; description: next job; `ScanStats.human_timeouts` counts skips and the summary prints `Skipped after an unsolved check/sign-in: N`. Window closed: no snapshot, scan stops with `Screenshot: none (window closed)`.
Verified by: tests/test_indeed_scanner.py::test_human_timeout_on_results_page_skips_page, ::test_human_timeout_in_description_skips_job, ::test_human_timeout_window_closed_stops_scan; tests/test_cli_scan.py::test_scan_window_closed_message, ::test_scan_summary_reports_dom_fallback_and_skips

**AC-33 (AC-C12): A failed snapshot doesn't change the scan's path.** Same rows, counters and page loads, plus one warning.
Verified by: tests/test_indeed_scanner.py::test_failed_snapshot_keeps_scan_path

**AC-34 (AC-C13): The snapshot is read-only** (`is_closed`, `screenshot`, `content` only).
Verified by: tests/test_snapshots.py::test_save_snapshot_only_reads_page, ::test_save_snapshot_window_closed_writes_nothing; plus code review.

**AC-35 (AC-C14): Local and gitignored.** `git check-ignore -v data/screenshots/x.png` prints `.gitignore:14:data/` (run 2026-11-28); `browser.py` imports no network module.
Verified by: manual check + code review.

**AC-36: A normal scan writes no snapshot.**
Verified by: tests/test_indeed_scanner.py::test_json_scan_takes_no_snapshot

**AC-37 (AC-C16): Guard.** 2 timeouts in a row (pages or jobs) stop the scan with `HumanActionTimeout` after the snapshot; the CLI prints `Scan stopped: 2 checks/sign-ins in a row were not solved; ... Screenshot: <path> (progress is saved)`. Timeout, a clear page, timeout carries on.
Verified by: tests/test_indeed_scanner.py::test_two_human_timeouts_in_a_row_stop_scan, ::test_timeout_count_resets_after_a_clear_page; tests/test_cli_scan.py::test_scan_guard_stop_message

**AC-38 (review F-1, 2026-11-28): Empty job JSON with cards.** When the first results page of a search shows cards but its job JSON lists no jobs, the scanner prints one warning, saves one `json_empty` snapshot, stores none of the cards and moves on to the next search. On a later page the same case is the end of results: no warning, no snapshot.
Verified by: tests/test_indeed_scanner.py::test_json_empty_on_first_page_snapshots_and_skips_search, ::test_json_empty_after_full_page_is_end_of_results

## 11. Open questions & assumptions

Inconsistencies with CLAUDE.md / docs:
1. ~~**No screenshots on failure.**~~ **Resolved 2026-11-28** by `changes/failure-screenshots` (BR-13, BR-14, AC-22..AC-37). Decided by the developer on 2026-11-27: all five failure points, PNG + HTML, keep 50, a `goto` error stops the scan, and a check/sign-in timeout **skips the item and carries on (OQ-4)**. That is a deliberate departure from the earlier "stop the scan" behaviour, limited by the guard (2 in a row stop). Still open: other Playwright errors outside the five points end in a traceback with no snapshot (A-7). A "no jobs match" marker for `parse.py` would avoid `no_cards` snapshots on a genuinely empty first page (follow-up).
2. **The cap counts descriptions, not new jobs.** The `max_new_jobs_per_run` name and the CLAUDE.md wording ("cap on new jobs") differ from the code (`stats.descriptions >= cap`, `scanner.py:138-139`). Descriptions back-filled for old rows count towards the cap, and new listings on the current page are still upserted after the cap is hit (they get a description on a later run).
3. **Page size assumption.** `config/searches.yaml` says "~15 jobs each" per page, but the scanner steps `start` by 10 and treats `< 10` listings as the last page (`scanner.py:25, 82`). If Indeed returns 15 cards per page with `start` stepping by 10, pages overlap (dedup absorbs this, but it wastes page loads). Needs a check against live Indeed.
4. **Selectors are not all in parse.py.** The `vjk=` and `/viewjob` URL markers and the composed card selector live in `scanner.py:159-174`, which goes against "all Indeed selectors in parse.py".
5. **Company size is not scraped.** CLAUDE.md lists "company size from Indeed's company page" as source 2 for company type, but the scanner never sets `company_size`. The column is always NULL for scanned jobs, so company type falls back to the MNC list, then the LLM.
6. **No daily scan cap.** CLAUDE.md requires a daily cap on *fills* (~25). Scans only have a per-run cap; repeated `jobbot scan` runs on one day are not limited. Assumption: this is intended, because the daily cap concerns applications. Confirm.

Risks / possible defects (not fixed):
7. `jobbot login` treats an unknown sign-in state (`logged_in=None`, DOM fallback) as signed out and fails with "still reports you as signed out" (`cli.py:302-305`).
8. In `jobbot login`, `load_searches` runs before the `try` block (`cli.py:268`), so a missing or invalid `searches.yaml` gives a traceback instead of the friendly `ConfigError` message.
9. `scan --decide` still runs the decide step after Ctrl+C. A user who pressed Ctrl+C may expect everything to stop.
10. `is_challenge` scans only the first 60,000 characters of the HTML. A challenge marker placed later is missed; a job description containing "verify you are human" near the top would be a false positive.
11. `posted_at` is the UTC date of `pubDate`, which can be one day off for IST users near midnight.
12. The job key is put into a CSS attribute selector without escaping (`scanner.py:161`). Indeed keys are hex today; a quote character would break the selector.
13. `ScanStats.logged_in` is overwritten per page and is `None` on the DOM path, so the summary may say "unknown" even when signed in.
14. `sponsored` is parsed but discarded. Sponsored cards are stored like any other.
15. Upserting an existing job refreshes only `easy_apply` and `salary`; title, company, location, snippet, `search_name` and `remote` keep their first-seen values.
16. **No partial summary when a scan stops** (review F-3 of `failure-screenshots`, deferred 2026-11-28). On a `Scan stopped` (page-load error, closed window, guard), no counts are printed (assumption A-4), and the timeout that trips the guard is not counted in `human_timeouts`. Changing this means changing A-4: the developer's call.

Assumptions:
- Indeed's embedded JSON structure observed on 2026-11-21 is still current. The fixture `tests/fixtures/indeed/search_page.html` is a trimmed real page (3 results, `loggedIn: false`).
- One scan at a time per Chrome profile (enforced only by Chrome's profile lock).

## 12. Dependencies

| Depends on | Why |
|---|---|
| `job-store` | `JobStore.upsert_listing`, `needs_description`, `get_by_key`, `set_description` (dedup + duplicate detection). |
| Config (`src/jobbot/config.py`) | `Settings.scan`, `Settings.browser`, `Search`, `load_searches`. |
| `src/jobbot/text.py` | `html_to_text` for snippets and descriptions. |
| `src/jobbot/models.py` | `Job` model. |
| External | Playwright + installed Google Chrome; BeautifulSoup; Indeed India; the user's manual presence for challenges and sign-in. |
| Downstream (uses this) | `job-store` / resume-matcher decide step (`jobbot decide`, `scan --decide`); later the planned dashboard and form filler. |
