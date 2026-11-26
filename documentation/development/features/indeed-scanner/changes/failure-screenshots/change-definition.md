# Change definition: indeed-scanner / failure-screenshots

> Lane B. Path: `documentation/development/features/indeed-scanner/changes/failure-screenshots/change-definition.md`.
> Source: `request.md` in this folder, including its "Decisions (2026-11-27, developer in chat)" section.

| | |
|---|---|
| Capability | `indeed-scanner` ([specification.md](../../specification.md)) |
| Status | **All open questions resolved 2026-11-27 (OQ-5 guard: yes; A-8 confirmed); awaiting plan approval** |
| Date | 2026-11-27 |
| Touches | Indeed integration (scanner failure handling), CLI scan output, `data/` files, config (`browser.screenshots_keep`, OQ-2). No DB, prompt or decision-schema change. |
| Plan | [implementation-plan.md](implementation-plan.md) |

All file:line references are to commit `c3677ba` (the scanner, browser, CLI and config code is
unchanged since then).

---

## 1. Current behaviour

No code writes screenshots. `grep -ri screenshot src tests config` finds nothing; only
`CLAUDE.md:191` and `.claude/rules/indeed.md:11` promise it (mistakes log M-001). The spec lists it
as out of scope / not implemented (spec section 3, Open question 1).

What happens today at each of the five failure points:

| # | Failure point | Where | What happens today |
|---|---|---|---|
| F-1 | `page.goto` raises (network error, timeout, Chrome error page) | `scanner.py:90` (`_load_results`), also reached from the retry reload at `scanner.py:154` | Not caught. The Playwright exception goes through `IndeedScanner.run` and is not caught by `cli.py:336-341` either (`playwright.Error` is not a `BrowserError`), so the CLI ends with a raw traceback. Rows committed so far are kept. No summary is printed and `--decide` does not run. Spec section 9, row "Navigation errors". |
| F-2 | Results page loads but has no job cards within 20 s | `scanner.py:92-98` | Prints `  no results on this page`; `_load_results` returns `None`; `run` breaks out of this search's paging (`scanner.py:76-77`) and moves to the next search. Nothing tells a genuine end of results apart from a changed page. |
| F-3 | Job-cards JSON missing or undecodable, DOM fallback used | `parse.py:49-54`, `parse.py:79-90` | Silent: `SearchPage.source == "dom"` and `logged_in = None`. The scanner never looks at `source`. Listings from the DOM are stored and processed normally. |
| F-4 | Description pane can't be read (after one retry) | `scanner.py:143-155` (retry), `scanner.py:132-134` (give up) | Prints `  ! no description: <title> @ <company>`, counts `description_failures`, leaves the description NULL (retried on the next scan), pauses, and carries on with the next card. A `PlaywrightError` per attempt prints `  browser error reading <jk>: ...` (`scanner.py:147-148`). |
| F-5 | `wait_for_human` times out on a Cloudflare check or sign-in page, or the window is closed | `browser.py:75-84`, called from `scanner.py:203-222` (via `scanner.py:91, 95, 152`) | `HumanActionTimeout` propagates out of `run`; the CLI prints `Scan stopped: Still blocked after Ns: ... (progress is saved)` (`cli.py:336-337`). No summary (`stats` stays `None`). `--decide` still runs (`cli.py:353-354`). |

Other relevant facts from the code:
- `Settings.data_dir` defaults to `<project>/data` and can be overridden (`config.py:15, 78, 134-138`).
  Nothing creates `data/screenshots/` today.
- `.gitignore` ignores the whole `data/` folder, so `data/screenshots/` is already gitignored.
- The scanner reports progress only through the `notify` callback (`scanner.py:53-57`); the CLI
  passes `_plain` (`cli.py:334`).
- `wait_for_human` is shared with `jobbot login` (`cli.py:272-278, 295-301`).

## 2. Proposed behaviour

### 2.1 Snapshot on failure
At each of the five failure points the scanner saves a **failure snapshot** ("screenshot set"):

- `data/screenshots/<timestamp>_<reason>[_<jobkey>].png`: a screenshot of the page.
- `data/screenshots/<timestamp>_<reason>[_<jobkey>].html`: the page HTML (`page.content()`), UTF-8.

Naming:
- `<timestamp>`: local time `YYYYMMDD-HHMMSS-mmm` (milliseconds), so names sort in time order and
  two failures in the same second don't collide.
- `<reason>`: one fixed slug per failure point:

  | Point | Slug |
  |---|---|
  | F-1 `goto` error | `goto_error` |
  | F-2 no cards | `no_cards` |
  | F-3 DOM fallback | `dom_fallback` |
  | F-4 description unreadable | `no_description` |
  | F-5 `wait_for_human` timeout | `human_timeout` |

- `_<jobkey>`: only for `no_description` (the Indeed `jk` of the job). The job key is scraped
  data, so it is **sanitised** before it goes into a file name: only `[A-Za-z0-9]` is kept, cut to
  32 characters; if nothing is left, the part is left out (safety rule 6, threat T-13).
- The folder is `Settings.data_dir / "screenshots"`, created if missing.

After saving, the scan output prints the path, for example
`  screenshot: data/screenshots/20261127-143005-123_no_description_a1b2c3d4e5f6.png (+ .html)`.
If only one of the two files could be written, only that one is named.

### 2.2 What the scan does after the snapshot

| Point | After the snapshot |
|---|---|
| F-1 `goto` error | **The scan stops.** The scanner raises a dedicated error that carries the screenshot path. The CLI prints `Scan stopped: page load failed: <first line of the error>. Screenshot: <path> (progress is saved)` instead of a traceback. Rows stored so far are kept and `--decide` runs afterwards, as for `HumanActionTimeout` today (spec AC-20, AC-21). |
| F-2 no cards | Skip the page: same as today, paging for this search stops and the scan moves to the next search. Snapshot only when it is the **first page** of a search, or the results reload inside the description retry (OQ-1, decided). A later empty page is the end of results: no snapshot. |
| F-3 DOM fallback | Carry on with the DOM listings (the fallback *is* the carry-on; nothing is skipped). Snapshot **once per scan run** (the first DOM-fallback page), and the end-of-scan summary gains `DOM fallback used on N pages (job JSON missing). Screenshot: <path>` (OQ-3, decided). |
| F-4 description unreadable | Skip the job: same as today (`! no description`, NULL description, retried next scan). One snapshot per job, taken once after the second attempt fails, not per attempt. If the job was given up because of a human-wait timeout (F-5) or because the retry reload showed no cards (F-2), that snapshot is the only one for the job. |
| F-5 `wait_for_human` timeout | **Skip the item and carry on** (OQ-4, decided by the developer 2026-11-27; a deliberate departure from today's "stop the scan"). Snapshot, print `! still blocked after Ns - skipped this page` (or `job`), then: on a results page, that page is skipped and paging for this search stops, the scan goes on with the next search (A-8); in the description reader, that job is skipped like F-4 and the scan goes on with the next job. The bot never interacts with the check; every later check waits for the human again (BR-3 polling unchanged). The summary gains `Skipped after an unsolved check/sign-in: N`. **Exception:** if the window was closed, no snapshot is attempted and the scan stops as today (`Scan stopped: The browser window was closed. Screenshot: none (window closed) (progress is saved)`). **Guard (OQ-5, open):** if accepted, 2 timeouts in a row stop the scan. |

### 2.3 Snapshot writing never breaks the scan
- Any error while taking the screenshot, reading the HTML, creating the folder, writing a file or
  pruning old sets is caught. The scan prints `  ! could not save screenshot: <reason>` and
  carries on with the behaviour in 2.2 exactly as if the snapshot had succeeded. For F-1 the scan
  still stops, with `Screenshot: not saved` in the message.
- The PNG and the HTML are written independently: a failed screenshot doesn't prevent the HTML,
  and the other way round.
- The screenshot call has a short timeout (assumption: 10 s) so a hung page can't stall the scan
  for Playwright's default 30 s.
- Taking a snapshot never navigates, clicks, scrolls or types. It only reads the current page
  (`page.screenshot`, `page.content`).

### 2.4 Retention
- After each saved snapshot, the newest **50** sets are kept and older sets are deleted. A set is
  all files that share one `<timestamp>_<reason>[_<jobkey>]` stem; age is taken from the
  timestamp in the name.
- Only files whose names match the jobbot snapshot pattern are counted or deleted. Any other file
  the user puts in `data/screenshots/` is left alone.
- The keep count is the config key **`browser.screenshots_keep`** (default 50, minimum 1; OQ-2,
  decided). The default lives in one place, `BrowserSettings` (M-004).

### 2.5 Where the code lives (for the plan; not a business rule)
The snapshot writer (naming, sanitising, writing, pruning) is not Indeed-specific and the planned
form filler needs the same thing, so it fits a platform-neutral helper (e.g. in `browser.py` or a
small new module), with the pure parts (file name, which files to prune) testable without a
browser. The scanner decides *when* to call it. No selectors or Indeed markers are added outside
`parse.py`. `wait_for_human` itself stays unchanged, so `jobbot login` is not affected; the
scanner adds the snapshot around its own calls. (The plan puts the helper in `browser.py`.)

## 3. Why
Indeed's pages will change. Today a changed page shows up as a silent DOM fallback, a "no results"
line, a failure count or a raw traceback, with nothing left to look at. Fixing the selectors in
`parse.py` then needs another scan, which means more page loads on the user's account. A
screenshot plus the HTML from the moment of failure lets the developer fix `parse.py` offline.
It also closes a gap where `CLAUDE.md` and `.claude/rules/indeed.md` promise behaviour that doesn't
exist (M-001).

## 4. Impact

| Area | Impact |
|---|---|
| Business rules (spec sections changed) | New BR (snapshot on failure: points, naming, retention, never crash). **BR-3 amended:** a human-wait timeout skips the current page or job instead of stopping the scan (OQ-4); a closed window still stops it (and, if OQ-5 is accepted, 2 timeouts in a row). Section 3: remove "Saving screenshots on failure" from out of scope. Section 5: add the snapshot files as a data entity and the new `ScanStats` counters. Section 6: "Waiting for human -> timeout" now leads to "item skipped" (window closed / guard: "Scan stopped"); new run state "stopped by page-load error". Section 9: rows "Navigation errors", "Results page shows no cards", "Mosaic JSON missing", "Description not read", "Human does not resolve" gain the snapshot; the `goto` row changes from traceback to a clean stop; the "Human does not resolve" row changes from stop to skip. Section 11: Open question 1 resolved. BR-9, BR-12 and AC-16, AC-21 keep their meaning. AC-9 changes only in what happens after the timeout. AC-20 now covers the page-load stop, the window-closed stop and (if accepted) the guard stop instead of every timeout. |
| Data (schema, statuses, `data/` files) | New files in `data/screenshots/` (`.png` + `.html`), at most `browser.screenshots_keep` (default 50) sets. **No DB change**, no migration, no new status. `architecture/data.md` row `screenshots/` changes from "planned" to the real format and retention. |
| CLI / dashboard | `jobbot scan` output gains `screenshot: <path>` lines, `! could not save screenshot` warnings and `! still blocked ... skipped this page/job` lines; the end-of-scan summary gains the DOM-fallback line (OQ-3) and the skipped-after-timeout line. A `goto` error now ends with a `Scan stopped: page load failed ...` message instead of a traceback, and `--decide` then runs. Exit code on that stop: 0 (A-3). A check/sign-in timeout no longer ends the scan, so a full `Scan done:` summary is printed. No new command or flag. No dashboard yet. |
| Prompts / decision schema | None. |
| Safety rules | No rule text is changed, but **one control is relaxed by the developer's explicit decision (OQ-4):** after a human-wait timeout the scan carries on to the next page or job instead of stopping, so Indeed can receive more requests while a check may still be showing. This sits in tension with safety rule 3 (protect the Indeed account) and is recorded as a deliberate developer decision; OQ-5 proposes a guard. Still true: the bot never automates past a check and every new check waits for the human again (rule 3, spec AC-10). Snapshots stay local in gitignored `data/` (rules 2 and 4). The snapshot only reads the page. File names built from the scraped job key are sanitised (rule 6, T-13). `architecture/security.md` T-4/T-6 (the skip behaviour), T-9 ("planned: screenshot") and T-14 get updated; see section 4.1. |
| Config | New key **`browser.screenshots_keep`** (int, default 50, minimum 1) in `config.py`, `config/settings.example.yaml` and `architecture/data.md` (OQ-2, decided). |
| Other capabilities | None changed. The planned `form-filler` can reuse the snapshot helper. `jobbot login` is unchanged. |
| Other open changes | `indeed-scanner/changes/scan-cap-and-paging` edits the same functions (`run`, `_load_results`, `_process_page` in `scanner.py`). Build order (decided 2026-11-27): after `job-store/changes/llm-timeout-stops-run`, and **before** `scan-cap-and-paging`, which is planned on top of this change. |
| Docs to update when built | indeed-scanner `specification.md` + `changelog.md`; `architecture/data.md`; `architecture/security.md` (T-4, T-6, T-9, T-14, Assets row "Screenshots"); `architecture/overview.md` (`browser.py` row); `.claude/rules/indeed.md`; `config/settings.example.yaml`; `CLAUDE.md` "Indeed scanning" notes (ask before editing); `.claude/mistakes/common-mistakes.md` M-001 evidence/streak. |

### 4.1 Safety notes
- **The HTML can contain personal data.** When the user is signed in, Indeed's page includes the
  account name and possibly the email address, plus page tokens tied to the session. The PNG can
  show the same. Treat `data/screenshots/` like the rest of `data/`: local only, gitignored, never
  attached to issues, commits, docs or chat.
- **Fixtures:** if a saved `.html` is later turned into a test fixture in `tests/fixtures/indeed/`,
  it must be scrubbed of personal data first (`.claude/rules/indeed.md`). Tests in this change use
  fake pages, not saved snapshots.
- **No extra traffic:** a snapshot makes no network request and loads no page; it only reads what
  is already on screen. It adds no page loads on the account.
- **Logs:** the scan output prints only the file path, never the HTML or anything from it
  (T-14).
- **Skip after a human-wait timeout (OQ-4).** This is the one place where the change relaxes an
  account-protection behaviour, at the developer's explicit request (2026-11-27). Today an unsolved
  check stops the scan, so no further request reaches Indeed. After this change the scan loads the
  next search page (or works on the next job) while the check may still be up. What still holds:
  the bot never clicks, types into or otherwise interacts with a check or sign-in page; each new
  check is detected and waits for the human again (`human_wait_timeout_s`); a closed window still
  stops the scan; pacing and the per-run cap are unchanged. Residual risk: R-7. Mitigation proposed
  in OQ-5 (stop after 2 timeouts in a row).

## 5. Acceptance criteria

Unless stated otherwise, tests use a **fake page object** (records calls; `goto`, `screenshot`,
`content`, `locator`, `title`, `url`, `is_closed` can be set to return values or raise
`playwright.sync_api.Error` / `TimeoutError`), a `tmp_path` data dir, a fake `notify` that collects
messages, a `tmp_path` `JobStore`, and `human_pause` patched to a no-op. No test opens a browser
or hits Indeed (M-002).

- **AC-C1: File naming.** For a fixed clock time, reason and job key, the snapshot stem is
  `<YYYYMMDD-HHMMSS-mmm>_<reason>[_<jobkey>]`, the files are `<stem>.png` and `<stem>.html` in
  `<data_dir>/screenshots/`, and the folder is created if missing.
  Verified by: unit test of the pure naming function with an injected clock, plus a writer test
  with the fake page and `tmp_path`.

- **AC-C2: Job key sanitising.** A job key with characters outside `[A-Za-z0-9]` (e.g.
  `../x"y`, `a/b\c`, a 100-character key, an empty key) gives a file name with only `[A-Za-z0-9]`
  in the key part, at most 32 characters, and no key part when nothing is left. The resulting path
  always stays inside `<data_dir>/screenshots/`.
  Verified by: parametrised unit test of the naming function.

- **AC-C3: PNG and HTML written.** With a fake page whose `screenshot(path=...)` writes bytes and
  whose `content()` returns `<html>...</html>`, both files exist with that content (HTML as UTF-8),
  and `notify` received one line containing the `.png` path.
  Verified by: unit test with the fake page and `tmp_path`.

- **AC-C4: Snapshot failure never crashes.** Each of these makes the writer return without raising
  and send one `! could not save screenshot` warning to `notify`: `screenshot` raises, `content`
  raises, the folder can't be created (e.g. `data_dir` points to an existing file). When only
  `screenshot` fails the `.html` is still written, and the other way round.
  Verified by: parametrised unit test with the fake page and `tmp_path`.

- **AC-C5: Retention.** With 52 existing snapshot sets (each `.png` + `.html`) plus one unrelated
  file (`notes.txt`) in the folder, saving one more leaves exactly the newest 50 sets (by name
  timestamp) and `notes.txt` untouched. A pruning error (e.g. a file that can't be deleted) gives
  a warning, not an exception.
  Verified by: unit test with `tmp_path` (files created with known timestamp names).

- **AC-C6: F-1 `goto` error stops the scan.** When the fake page's `goto` raises, `run` saves a
  `goto_error` snapshot, loads no further pages, makes no further clicks, and raises the dedicated
  page-load error carrying the screenshot path (or none if the snapshot failed). Rows upserted
  before the error stay in the store.
  Verified by: scanner unit test (fake page, `tmp_path` store, two searches; the error is raised
  on the first `goto` and on a later `goto` after one page was stored).

- **AC-C7: F-1 CLI message.** `jobbot scan` turns the page-load error into
  `Scan stopped: page load failed: <first line>. Screenshot: <path> (progress is saved)`, prints
  no traceback, and still runs the decide step when `--decide` is given.
  Verified by: CLI test with `typer.testing.CliRunner`, with `open_browser` and `IndeedScanner.run`
  monkeypatched (the run raises the page-load error) and `_run_decide` patched to record the call.

- **AC-C8: F-2 no cards (OQ-1 decided).** When a results page shows no cards, the scanner prints
  `no results on this page`, stops paging this search and continues with the next search. A
  `no_cards` snapshot is saved only when it is the **first page** of a search, or the results
  reload inside the description retry (then that job is given up with no further snapshot). An
  empty later page (after a full page) saves nothing.
  Verified by: scanner unit tests (fake page where `wait_for_selector` raises `TimeoutError` and the
  card count is 0): two searches with an empty first page (snapshot, second search still loaded);
  a full first page then an empty second page (no snapshot); a check that clears during a
  description read followed by an empty reload (one `no_cards` snapshot, job skipped).

- **AC-C9: F-3 DOM fallback (OQ-3 decided).** When a results page has cards but no job-cards JSON,
  the listings from the DOM are stored and processed as today, and a `dom_fallback` snapshot is
  saved **once per scan run**: a second DOM-fallback page in the same run saves nothing. The
  end-of-scan summary prints `DOM fallback used on N pages (job JSON missing). Screenshot: <path>`
  with N counting every DOM-fallback results page of the run.
  Verified by: scanner unit test whose fake page returns HTML without the mosaic marker for two
  pages; CLI test for the summary line.

- **AC-C10: F-4 description unreadable.** When a job's description can't be read after both
  attempts, exactly one `no_description_<jobkey>` snapshot is saved for that job, the job keeps a
  NULL description, `description_failures` goes up by 1, and the scanner moves on to the next job
  on the page.
  Verified by: scanner unit test (fake page whose card locator returns count 0 for one job key and
  a readable pane for the next).

- **AC-C11: F-5 `wait_for_human` timeout skips the item and carries on (OQ-4 decided).** When
  `wait_for_human` raises `HumanActionTimeout` inside the scanner and the window is still open:
  - a `human_timeout` snapshot is saved and `! still blocked after Ns - skipped this page|job` is
    printed;
  - **on a results page** (the check right after `goto`, or the late check after the card wait),
    that page is skipped, paging for this search stops, and the scan continues with the next
    search (A-8);
  - **in the description reader**, that job is skipped (NULL description, `description_failures`
    +1, `! no description` line, no extra `no_description` snapshot), and the scan continues with
    the next job on the page;
  - `ScanStats.human_timeouts` counts the skipped items; `run` returns normally and the summary
    prints `Skipped after an unsolved check/sign-in: N`;
  - while waiting, the bot still only polls the page; every later check waits for the human again
    (spec AC-9, AC-10).

  When the window was closed, no snapshot is attempted and the scan **stops** as today:
  `HumanActionTimeout` reaches the CLI, which prints
  `Scan stopped: The browser window was closed. Screenshot: none (window closed) (progress is saved)`
  and still runs `--decide`.
  Verified by: scanner unit tests with `wait_for_human` patched (results-page timeout, description
  timeout, window closed); CLI wording via `CliRunner` as in AC-C7.

- **AC-C12: Snapshot failure doesn't change the scan's path.** For F-2 and F-4, a fake page whose
  `screenshot` and `content` both raise during the snapshot gives the same stored rows, counters
  and next actions as a run where the snapshot succeeds, plus one warning line each.
  Verified by: the AC-C8 and AC-C10 tests run a second time with a failing snapshot.

- **AC-C13: Snapshot is read-only.** While taking a snapshot the scanner calls only
  `screenshot`, `content` and `is_closed` on the page: no `goto`, `click`, `fill`, `type`,
  `press`, `go_back` or `reload`.
  Verified by: assertion on the fake page's call log in the writer test; plus code review in
  `/review-feature` (spec AC-10 still holds).

- **AC-C14: Stays local and gitignored.** `data/screenshots/` is ignored by Git and the snapshot
  code makes no network call.
  Verified by: `git check-ignore -v data/screenshots/x.png` prints the `data/` rule (run in the
  review, output pasted); code review that the helper imports nothing network-related.

- **AC-C15: Retention count source (OQ-2 decided).** The keep count is `browser.screenshots_keep`,
  50 by default; setting it to 3 in a test `Settings` keeps 3 sets; a value below 1 is rejected
  by `BrowserSettings` validation.
  Verified by: unit tests (AC-C5 variant, config validation).

- **AC-C16: Guard: 2 human-wait timeouts in a row stop the scan. (OQ-5 accepted by the developer
  on 2026-11-27.)** A timeout counts as "in a row" when no blocker check
  (`_handle_blockers`) has completed without a timeout since the previous one, i.e. no page or job
  got past a check in between. On the 2nd such timeout the `human_timeout` snapshot is saved and
  the scan stops with `HumanActionTimeout` (message names the 2 unsolved checks); the CLI prints
  `Scan stopped: ... Screenshot: <path> (progress is saved)` and still runs `--decide`. A timeout,
  then a page that loads with no check (or a solved check), then another timeout does **not** stop
  the scan. The limit is a named constant (2).
  Verified by: scanner unit tests (two timeouts in a row stop; timeout / clear / timeout carries on).

Spec ACs touched: AC-20 now covers the page-load stop (AC-C6, AC-C7), the window-closed stop and,
if accepted, the guard stop (AC-C16); a plain check/sign-in timeout no longer stops the scan
(AC-C11). AC-9 changes only in what follows the timeout. AC-10, AC-16 and AC-21 are unchanged in
meaning.

## 6. Migration and compatibility
- **`data/jobs.db`:** no schema change, no migration, no status change. Existing rows are untouched.
- **Cached resume profiles, `decisions.jsonl`:** not touched.
- **`data/screenshots/`:** new folder, created on the first snapshot. Nothing exists there today,
  so retention starts from zero.
- **Config:** existing `config/settings.yaml` files keep working. The new key
  `browser.screenshots_keep` is optional with default 50.
- **CLI:** output gains lines; no flag changes. Behaviour changes visible to scripts: a `goto`
  error ends in a message instead of a traceback (exit code 0, A-3); a check/sign-in timeout no
  longer ends the scan (OQ-4), so the scan continues and prints the full summary.

## 7. Open questions and assumptions

### Open questions

- **OQ-1: Tell "no cards" apart from a genuine end of results?** **Decided (developer in chat,
  2026-11-27):** save `no_cards` only when the **first page** of a search has no cards, and on the
  results reload inside the description retry (`scanner.py:154`), where cards were there a moment
  before. A later empty page is the end of results, as today, and saves nothing. Follow-up (not in
  this change): once a real Indeed "no jobs match" page has been saved, add its marker to
  `parse.py` and skip the snapshot when that marker is present.
  *Affects:* AC-C8.

- **OQ-2: Make the retention count a config key?** **Decided (developer in chat, 2026-11-27):**
  yes, **`browser.screenshots_keep`** (default 50, minimum 1). `browser.` rather than `scan.`
  because the planned form filler will write to the same folder.
  *Affects:* AC-C15, `config.py`, `settings.example.yaml`, `data.md`.

- **OQ-3: DOM-fallback snapshot every time, or once per run?** **Decided (developer in chat,
  2026-11-27):** **once per scan run** (the first DOM-fallback page), plus one summary line at the
  end: `DOM fallback used on N pages (job JSON missing). Screenshot: <path>`.
  *Affects:* AC-C9.

- **OQ-4: After a `wait_for_human` timeout, stop or carry on? (safety)** **Decided (developer in
  chat, 2026-11-27): skip and carry on.** Save the screenshot and HTML, skip that item (the results
  page, or the job) and continue the scan, instead of stopping it. The developer chose this knowing
  it means more Indeed requests while a check may still be showing. This is a **deliberate
  developer decision that departs from the earlier "stop" behaviour** (spec BR-3 / AC-20 and this
  draft's earlier recommendation) and is in tension with safety rule 3 (protect the Indeed
  account). The bot still never automates past a check: every new check waits for the human
  again, and a closed window still stops the scan. See section 4.1 and R-7.
  *Affects:* section 2.2 row F-5, AC-C11, spec BR-3 / AC-9 / AC-20 / section 6 / section 9.

- **OQ-5: Guard: stop the scan after 2 consecutive human-wait timeouts? Decided (developer in
  chat, 2026-11-27): yes, build the guard (step 7, AC-C16).** With OQ-4, an unsolved check (e.g. the user is away) no
  longer ends the scan. The next item hits the same check, waits another `human_wait_timeout_s`
  (default 300 s), times out, and the scan moves on again, sending a results-page request for each
  further search while Indeed is challenging the account.
  *Recommendation:* **yes.** Two timeouts in a row (no page or job got past a check in between)
  stop the scan with `HumanActionTimeout`, exactly like the old behaviour, after the snapshot. A
  single unsolved check is still skipped as decided in OQ-4, so the developer's choice holds for
  the one-off case. The limit is a named constant (2), not a config key, to keep the change small.
  *Affects:* AC-C16 (dropped if the guard is declined) and one optional step in the plan.

### Assumptions (A-1..A-7 accepted by the developer in chat, 2026-11-27)
- **A-1:** Full-page screenshots (`full_page=True`), with a 10 s screenshot timeout. Viewport-only
  would be smaller; full page shows more of a changed layout.
- **A-2:** Timestamps use local time (consistent with `first_seen_at`/`updated_at` in `data.md`).
- **A-3:** The page-load stop (F-1) exits with code 0, like the `HumanActionTimeout` stop today
  (`cli.py:336-337`), so `--decide` can run and the behaviour matches the other "Scan stopped"
  case.
- **A-4:** No partial `Scan done:` summary is added on a stop; that is today's behaviour for
  `HumanActionTimeout` too and is out of scope here.
- **A-5:** Paths are printed relative to the project root when the data dir is inside it, else
  absolute.
- **A-6:** `jobbot login` gets no snapshots in this change (the request is about the scanner).
- **A-7:** Other unexpected Playwright errors outside the five points (e.g. a non-timeout error
  from `wait_for_selector` at `scanner.py:93`, or `page.content()` failing at `scanner.py:100`)
  are out of scope and still end in a traceback. Recorded as a risk below.
- **A-8 (from planning OQ-4; confirmed by the developer in chat, 2026-11-27):** "skip the page"
  after a human-wait timeout on a results page works like F-2: paging for that search stops and
  the scan goes on with the next search, rather than loading the next page of the same search.
  This reuses the existing "no results" path in `run` (smaller change, R-4) and avoids paging
  deeper into a search that just got challenged.

### Risks
- **R-1: Personal data on disk.** Snapshots of a signed-in session hold the user's name/email and
  page tokens. Mitigated by keeping them in gitignored `data/`, retention of 50, and never printing
  their content. Residual risk: the user copies one into an issue or a fixture; the spec and
  `security.md` will say to scrub first.
- **R-2: Disk use.** Full-page PNG + HTML can be 1–5 MB per set, so up to ~250 MB at 50 sets.
  Acceptable locally; lower `browser.screenshots_keep` if needed.
- **R-3: Snapshot slows a failing scan.** Each snapshot can take up to the screenshot timeout. With
  OQ-1 and OQ-3 as decided, snapshots are rare.
- **R-4: Merge conflict with `scan-cap-and-paging`.** Both change `scanner.py` `run` /
  `_load_results` / `_process_page`. Build order: this change first, then `scan-cap-and-paging`
  on top of it (see the plan).
- **R-5: Untested scanner loop today.** The scanner has no tests yet (M-002); this change adds the
  first fake-page scanner tests. The fake page must stay close to Playwright's real API or the tests
  give false confidence; keep it minimal and typed.
- **R-6: Other uncaught errors (A-7)** still give tracebacks with no snapshot. A later change could
  widen the net.
- **R-7: More requests while Indeed is challenging the account (OQ-4).** Without the guard, an
  unattended scan that hits a check keeps going: each remaining job on the page waits out its own
  timeout (no page load, but up to `human_wait_timeout_s` each), then each further search loads its
  first results page while the check may still be up. That is the pattern that tends to escalate
  Cloudflare checks. Accepted by the developer; mitigated by OQ-5 if accepted.
