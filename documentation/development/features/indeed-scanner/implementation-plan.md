# Implementation plan: indeed-scanner

Status: As-built (retroactive).

Reconstructed on 2026-11-26 from the code at commit `c3677ba`. It describes what was built,
not a proposal. Spec: [specification.md](specification.md).

---

## 1. Affected layers

| Layer | Impact |
|---|---|
| DB | **No schema of its own.** Writes to the `jobs` table through the `job-store` API only (`upsert_listing`, `needs_description`, `get_by_key`, `set_description`). From the SQL-migrations change on, the schema lives in `src/jobbot/migrations/` (see job-store). |
| Browser | `src/jobbot/browser.py`: headed persistent Chrome (`launch_persistent_context`, `channel="chrome"`), `human_pause`, `wait_for_human`, `BrowserError`, `HumanActionTimeout`. |
| Parsing | `src/jobbot/platforms/indeed/parse.py`: pure functions (no browser), unit-testable. Holds the selectors, mosaic-JSON parsing, DOM fallback, description parsing and blocker detection. |
| Pipeline / orchestration | `src/jobbot/platforms/indeed/scanner.py`: `search_url`, `IndeedScanner.run` (searches -> pages -> listings -> descriptions), pacing, cap, blocker handling, `ScanStats`. |
| CLI | `src/jobbot/cli.py`: `jobbot login`, `jobbot scan` (`--search/-s`, `--pages`, `--decide`). |
| Config | `config/searches.yaml` (searches + defaults); `config/settings.example.yaml` -> `config/settings.yaml` (`scan.*`, `browser.*`); `src/jobbot/config.py` (`Search`, `ScanSettings`, `BrowserSettings`, `load_searches`). |
| API / Frontend | None (CLI tool; the dashboard is planned). |
| Security | Indeed account protection (headed, manual login, never bypass challenges, pacing). Local-only data; `browser_profile/` is gitignored. |
| Tests | `tests/test_indeed_parse.py`, plus the fixture `tests/fixtures/indeed/search_page.html` (a trimmed real results page). |
| Docs | `CLAUDE.md` section "Indeed scanning (step 2)"; this folder. |

## 2. File / module map

| File | Responsibility | Key symbols |
|---|---|---|
| `src/jobbot/browser.py` | Browser lifecycle and human hand-off | `open_browser` (L31), `human_pause` (L56), `wait_for_human` (L60), `_safe` (L87) |
| `src/jobbot/platforms/indeed/parse.py` | Indeed HTML/JSON -> models; all selectors | `MOSAIC_MARKER`, `SEL_*`, `CHALLENGE_*`, `SIGNIN_URL_PARTS` (L21-32); `parse_search_page` (L49); `parse_description` (L57); `is_challenge` (L64); `is_signin` (L72); `_mosaic_model` (L79); `_from_mosaic` (L93); `_from_dom` (L118); `_dedupe` (L144) |
| `src/jobbot/platforms/indeed/scanner.py` | Scan loop | `RESULTS_PER_PAGE_STEP=10`, `DESCRIPTION_TIMEOUT_S=15`; `ScanStats`; `search_url` (L42); `IndeedScanner.run` (L62), `_load_results` (L89), `_process_page` (L102), `_cap_reached` (L138), `_read_description` (L143), `_click_and_read` (L157), `_handle_blockers` (L203) |
| `src/jobbot/cli.py` | Commands | `login` (L261), `scan` (L310), `_store` (L253), `_plain` (L257) |
| `src/jobbot/config.py` | Settings/searches models | `BrowserSettings` (L57), `ScanSettings` (L65), `Search` (L82), `load_searches` (L92) |
| `src/jobbot/text.py` | HTML -> text | `html_to_text`, `normalize` |
| `src/jobbot/models.py` | Shared `Job` model | `Job`, `Job.description_sha256` |
| `src/jobbot/db.py` | Persistence (job-store capability) | see job-store plan |

## 3. Config keys used

| Key | Default | Used for |
|---|---|---|
| `scan.base_url` | `https://in.indeed.com` | Search, viewjob and login URLs (trailing `/` stripped) |
| `scan.delay_min_s` / `scan.delay_max_s` | 2.5 / 6.0 | Pause after each description attempt; x2 between result pages |
| `scan.max_new_jobs_per_run` | 80 | Per-run cap on **descriptions read** |
| `browser.channel` | `chrome` | Playwright channel (installed Google Chrome) |
| `browser.profile_dir` | `browser_profile` (project-relative) | Persistent Chrome profile (session cookies) |
| `browser.human_wait_timeout_s` | 300 | Wait limit for challenge / sign-in during a scan |
| `searches[].name/query/location/max_pages/fromage/sort/extra_params` | see `config/searches.yaml` `defaults` (`max_pages: 2`, `fromage: 3`, `sort: date`) | Search URL building and paging |
| CLI `login --timeout-min` | 10 | Wait limit for the manual sign-in and for the challenge during the probe |

Hard-coded constants (not configurable): 10 results per page step, 15 s description timeout,
20 s wait for result cards, 2 s blocker poll interval, 1.0–2.5 s settle pause, 0.4–1.2 s pre-click pause,
1366x900 viewport, 60,000-char challenge scan window.

## 4. Test plan (AC -> tests)

Run on 2026-11-26: `.venv\Scripts\python -m pytest -q tests/test_indeed_parse.py tests/test_db_pipeline.py` gave **18 passed** (6 in `test_indeed_parse.py`, 12 in `test_db_pipeline.py`).

| AC | Test | Status |
|---|---|---|
| AC-1 Search URL | `tests/test_indeed_parse.py::test_search_url` | Covered |
| AC-2 Searches config | — | **Gap** |
| AC-3 JSON parsing | `tests/test_indeed_parse.py::test_parse_real_search_page_json` | Covered |
| AC-4 Snippet to text | `tests/test_indeed_parse.py::test_parse_real_search_page_json` | Covered |
| AC-5 DOM fallback | `tests/test_indeed_parse.py::test_dom_fallback_when_json_missing`, `::test_broken_json_falls_back_to_dom` | Covered |
| AC-6 In-page dedup | `tests/test_indeed_parse.py::test_dom_fallback_when_json_missing` | Partial (DOM path only) |
| AC-7 Description parsing | `tests/test_indeed_parse.py::test_parse_description` | Covered |
| AC-8 Blocker detection | `tests/test_indeed_parse.py::test_challenge_and_signin_detection` | Covered (the `/account/login` and `secure.indeed.com/account/login` variants are not asserted) |
| AC-9 Wait for human | — | **Gap** (manual) |
| AC-10 Never automates past blockers | — | **Gap** (code review) |
| AC-11 Cross-run dedup | `tests/test_db_pipeline.py::test_upsert_is_idempotent` | Partial (store level; scanner loop untested) |
| AC-12 Description reading | — | **Gap** (manual) |
| AC-13 Duplicate descriptions | `tests/test_db_pipeline.py::test_duplicate_descriptions` | Partial (store level) |
| AC-14 Pacing | — | **Gap** |
| AC-15 Per-run cap | — | **Gap** |
| AC-16 Paging stop | — | **Gap** |
| AC-17 Browser profile | — | **Gap** (manual) |
| AC-18 Login | — | **Gap** (manual) |
| AC-19 Scan CLI | — | **Gap** (manual) |
| AC-20 Interrupted scans keep progress | — | **Gap** (manual) |
| AC-21 Scan then decide | — | **Gap** (manual) |

Suggested future tests (not written): `load_searches` validation; `IndeedScanner` driven by a fake `Page` (or a Playwright run against local fixture HTML) for the cap, paging stop, description retry and `needs_description` skip; `wait_for_human` with a fake page and a short timeout; `is_challenge` 60k-char boundary.

## 5. Implementation steps (reconstructed)

1. Add `BrowserSettings` and `ScanSettings` to `config.py`, and the `Search` model with `load_searches` (defaults merge, unique names).
2. `browser.py`: persistent headed Chrome context; `human_pause`; `wait_for_human` with a poll loop, timeout and window-closed detection.
3. Capture a real Indeed India results page and trim it into `tests/fixtures/indeed/search_page.html`.
4. `parse.py`: mosaic-JSON extraction (`raw_decode` from the marker), field mapping, DOM fallback, in-page dedup, `parse_description`, `is_challenge`, `is_signin`; unit tests in `tests/test_indeed_parse.py`.
5. `scanner.py`: `search_url`; the results-page loader with blocker handling; listing upsert into the job store; description reading via the side pane (with the `/viewjob` fallback and one retry); pacing; per-run cap; `ScanStats`.
6. Observed on 2026-11-21 that logged-out `/viewjob` loads redirect to sign-in and that Cloudflare challenges appear after a few loads. Added sign-in/challenge detection with `wait_for_human` and the `jobbot login` command (manual sign-in, `loggedIn` check).
7. `cli.py`: the `scan` command with `--search`, `--pages`, `--decide`, the summary output and the "progress is saved" handling.
8. Documented in CLAUDE.md (Step 2).

## 6. Risks

| Risk | Impact | Current mitigation | Notes |
|---|---|---|---|
| Indeed changes its embedded JSON key or structure | JSON path fails | Automatic DOM fallback | The fallback loses salary, posting date and snippet, and `logged_in` becomes unknown. No alert is raised. |
| Indeed changes card/pane markup (`a[data-jk]`, `#jobDescriptionText`, `vjk=` URL param) | No results or every description fails | Selectors are mostly centralised in `parse.py` | Fails quietly (counts only); **no screenshots** despite CLAUDE.md. |
| Cloudflare challenges / bot detection | Scan blocked | Headed real Chrome, real profile, random delays, wait-for-human | Challenges are expected; never bypass. A timeout stops the scan and progress is kept. |
| Indeed account restriction or ban | Loss of the user's account | Manual login, slow pacing, per-run cap, visible window | No daily scan cap; repeated runs can add up. |
| Page-size mismatch (10 vs ~15 per page) | Overlapping pages, wasted loads | Dedup by job key | See spec Open question 3. |
| Profile lock (two jobbot browsers at once) | Launch failure | `BrowserError` with a hint | — |
| SQLite writes during a long scan | Lock contention if `jobbot decide` runs at the same time | Commit after each write | See the job-store plan. |
| Unhandled Playwright navigation errors | Scan ends with a traceback | Progress is committed | Consider catching them and saving a screenshot. |

## 7. Related ADRs

- `documentation/development/decisions/ADR-0004-human-approval-never-auto-submit.md`: the human-in-the-loop principle, which the scanner applies to sign-in and challenges (the bot waits; the user acts).
- `documentation/development/decisions/ADR-0003-sql-migration-files.md`: the schema of the table the scanner writes to now lives in migration files.
- Candidate ADRs not yet written: "Parse Indeed results from embedded JSON with a DOM fallback"; "Scan and decide as separate commands"; "Headed persistent Chrome profile with manual login".
