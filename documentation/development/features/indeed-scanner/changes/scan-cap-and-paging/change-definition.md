# Change definition: indeed-scanner / scan-cap-and-paging

> Lane B. Path: `documentation/development/features/indeed-scanner/changes/scan-cap-and-paging/change-definition.md`.
> Source: [request.md](request.md), including the developer's decisions of 2026-11-27 (option (c);
> OQ-2 to OQ-5 decided in chat). Plan: [implementation-plan.md](implementation-plan.md).

| | |
|---|---|
| Capability | `indeed-scanner` ([specification.md](../../specification.md)) |
| Status | **Open questions resolved 2026-11-27 except OQ-1 (real scan); awaiting plan approval** |
| Date | 2026-11-27 |
| Governance | standard: `implementation-plan.md` and a human-written `plan-approval.md` come before any code |
| Touches | Indeed integration, account-protection pacing (safety rule 3), shared `config.py`. No DB, prompt or decision-schema change |

All file:line references are to the working tree on 2026-11-27 (same code as commit `c3677ba`
for the files cited).

---

## 1. Current behaviour

### 1.1 The per-run cap
- **Setting:** `ScanSettings.max_new_jobs_per_run: int = 80`, commented "stop fetching
  descriptions after this many new jobs" (`src/jobbot/config.py:69`).
  `config/settings.example.yaml:30` says "cap on new job descriptions fetched per `jobbot scan`".
  Spec BR-8 and AC-15 document it as a cap on **descriptions read**.
- **What the code counts:** `_cap_reached` compares `stats.descriptions` with the setting
  (`src/jobbot/platforms/indeed/scanner.py:138-139`). `stats.descriptions` goes up only when a
  description was read **successfully** (`scanner.py:125`). So the cap does not count:
  - result-page loads (`page.goto`, `scanner.py:90`), including loads that show no results
    (`scanner.py:92-98`);
  - failed description attempts (`scanner.py:132-134`) and the second attempt of the retry loop
    (`scanner.py:144`);
  - the results reload after a human wait (`scanner.py:152-154`).
- It does count descriptions back-filled for **older** rows that still had no description
  (`needs_description`, `scanner.py:117`, `src/jobbot/db.py:273-275`), although those are not new jobs.
- **Where it is checked:** before each results page (`scanner.py:68-72`) and before each
  description (`scanner.py:119-120`). After the inner `break`, `run` still does the 2x between-page
  pause (`scanner.py:84`) and only stops at the next loop turn.
- **Reporting gap:** if the cap is reached on the last page of the last search, the loop just ends,
  `stopped_early` is never set, and the summary does not say the cap stopped anything.
- **Effect:** the number of Indeed requests in one run is not bounded by the setting. With the
  default searches (7 searches x `max_pages: 2`, `config/searches.yaml:4-30`) a run can make
  80 successful reads, plus up to 14 result-page loads, plus every failed attempt (up to 2 clicks
  and a reload each).

### 1.2 Paging
- `RESULTS_PER_PAGE_STEP = 10` (`scanner.py:25`) is used for two different things:
  - the `start` offset: `start = page_index * 10` (`scanner.py:46-47`);
  - the last-page test: fewer than 10 distinct listings means "last page" (`scanner.py:82-83`).
- `config/searches.yaml:5` says "~15 jobs each" per page. One of the two is wrong. The real page
  size and `start` step on `in.indeed.com` have not been checked. The only saved page
  (`tests/fixtures/indeed/search_page.html`) was trimmed to 3 jobs (`tests/test_indeed_parse.py:20`).
- `tests/test_indeed_parse.py:98` pins `start=20` for page index 2.
- If Indeed shows 15 cards and the step is 10, every page after the first overlaps the previous one
  by 5 cards. The job store's unique key absorbs the duplicates, but each overlapping page is a
  wasted load. A full 15-card page is never "short", so the bot may also load one page past the end.

### 1.3 Reporting
- `jobbot scan` prints `Scan done: P pages, L listings, N new jobs, D descriptions read, F failed,
  U duplicates | signed in: ...` and, if set, `Stopped early: reached max_new_jobs_per_run=N`
  (`src/jobbot/cli.py:343-352`).
- `P pages` (`stats.pages`) counts only loads that returned listings (`scanner.py:78`), so loads
  with no results are not reported.

### 1.4 Config validation
- `ScanSettings` (`config.py:65-69`) has no `model_config`, so pydantic's default `extra="ignore"`
  applies. **Unknown keys in `config/settings.yaml` are silently dropped.** This holds for every
  `Settings` section. Only `Profile` sets `extra` (`"allow"`, `config.py:110`).
- `load_settings` calls `Settings.model_validate` without catching pydantic's `ValidationError`
  (`config.py:131-133`). A bad value (e.g. `max_new_jobs_per_run: abc`) ends `jobbot scan` with a
  traceback instead of the friendly `ConfigError` path (`cli.py:319-323`).

## 2. Proposed behaviour

Decided by the developer on 2026-11-27: **option (c)**, one per-run cap on every Indeed page action.
It replaces `scan.max_new_jobs_per_run`.

### Business rules (replace spec BR-8 and BR-9; BR-7 pacing is unchanged)

**BR-C1: Page action.** A page action is a request the bot itself starts on Indeed. It is counted
when the bot starts it, whatever the outcome:
- **Result-page load:** every `page.goto` of a search-results URL (today `scanner.py:90`), including
  a load that shows no results or a challenge.
- **Description read:** every attempt to read one job's description: clicking its card
  (`scanner.py:164-167`), or reading the pane when that card is already open (`scanner.py:159`).
  If the click opens a full `/viewjob` page, that page and the `go_back` after it
  (`scanner.py:174-177`) are part of the same action.
- **Retries and reloads count (OQ-5, decided):** the second description attempt (`scanner.py:144`)
  counts as another description read, and the results reload after a human wait
  (`scanner.py:152-154`) counts as another result-page load. An attempt counts even when it makes
  no request in the end (e.g. the card is no longer on the page): the rule is "every attempt".
- **After a skipped item:** the change `failure-screenshots` makes the scanner skip the item and
  carry on after a `wait_for_human` timeout. Every load, reload or click the scanner makes after
  such a skip is an ordinary page action and counts under the rules above.
- **Not counted:** polling while `wait_for_human` waits (`src/jobbot/browser.py:76-83`; it only
  reads the page already loaded), anything the user does in the window, parsing an already-loaded
  page, failure snapshots (they only read the page), DB writes, and pauses.

**BR-C2: The cap.** `scan.max_page_actions_per_run` (a positive integer; default **80**, OQ-2) limits
page actions in one `jobbot scan` run, across all searches. Before starting any page action the
scanner checks the count. If `page_actions >= max_page_actions_per_run`, the action is **not
started**. So a run never makes more page actions than the cap.

**BR-C3: Clean stop.** When the cap refuses an action, the scan stops:
- no further page loads, clicks or pauses in this run;
- `run` returns normally (no exception); the browser closes as usual;
- everything already stored stays (writes are committed immediately, spec BR-12). Listings of the
  page already loaded are still stored, because storing them makes no request. Jobs left without a
  description get one on a later run (spec BR-6);
- `--decide` still runs afterwards (spec BR-11, unchanged);
- exit code 0. Reaching the cap is a normal end of a run, as today.

**BR-C4: Reporting.** The scan summary always shows the page actions used against the cap. If the
cap refused an action, it also prints a `Stopped early` line naming the setting, the cap and the
split between result-page loads and description reads. A run whose planned work used exactly the
cap and needed nothing more is **not** "stopped early".

**BR-C5: Paging (pending real-scan verification, OQ-1).** Two named constants describe Indeed's
paging, in `src/jobbot/platforms/indeed/parse.py` next to the other Indeed facts (they describe
Indeed, so they are not user settings):
- `PAGE_STEP`: the `start` increment between result pages. The search URL uses
  `start = page_index * PAGE_STEP`.
- `FULL_PAGE_SIZE`: the number of distinct listings on a full page. A page with fewer distinct
  listings is the last page of that search.

Both are set to the values the developer observes on 2026-11-28. A comment gives that date and
points to the observation note. The names are placeholders; the plan may choose others.
`config/searches.yaml` states the same number of jobs per page.

**BR-C6: Config errors (OQ-3, decided).** An invalid `scan.max_page_actions_per_run` (not an
integer, or below 1) gives a `ConfigError` that names the key; `jobbot scan` prints it and exits 1.
- The old key `scan.max_new_jobs_per_run` is **rejected**: `load_settings` raises a `ConfigError`
  saying it was renamed to `scan.max_page_actions_per_run`, that the new cap counts result-page
  loads plus description reads, and to rename it in `config/settings.yaml`. There is no alias.
- `ScanSettings` forbids unknown keys (`extra="forbid"`), so a misspelt key under `scan:` also
  fails loudly instead of falling back to the default. The other sections (`llm`, `matching`,
  `browser`, the top level) keep ignoring unknown keys; this change does not widen that.
- `load_settings` turns pydantic's `ValidationError` into a `ConfigError` that lists each bad key
  by its dotted path. This applies to every section, so e.g. `llm.timeout_s: abc` also gets a
  clear message instead of a traceback.

**BR-C7: Early stop for date-sorted searches (OQ-4, decided).** For a search with `sort: date`, if
a loaded results page has **no new listings and no listings that still need a description**, the
scanner loads no further pages of that search and moves on to the next search. It prints one line
saying so. Searches with any other `sort` (e.g. `relevance`) page on as before, because later pages
can still hold new jobs.

Unchanged: `max_pages` and `--pages` still bound the pages per search; a page with no cards within
20 s still ends that search's paging (and now counts as one page action); delays and the
`wait_for_human` flow are unchanged.

## 3. Why

The cap and the paging are what limit the bot's activity on Indeed per run, and so the risk to the
user's account (safety rule 3). Today the cap's name, comment, example file and spec each say
something different from what the code counts. Page loads are not limited by the cap at all. The
page step is a hard-coded number that disagrees with `searches.yaml` (common-mistakes M-004).
After this change, the one setting bounds **all** bot-initiated Indeed traffic in a run, its name
says exactly that, a test proves where it stops, and the paging numbers are the verified ones.

## 4. Impact

| Area | Impact |
|---|---|
| Business rules (spec sections changed) | BR-8 is replaced by BR-C1 to BR-C4 and BR-C6. BR-9 is replaced by BR-C5 and BR-C7. Spec section 5 (`ScanStats` gains page-action counts), section 6 ("Stopped early" state, early stop of a date-sorted search), section 8/9 (config validation and error cases), section 10 (AC-1, AC-15, AC-16, AC-19 change; see section 5 below) and section 11 (open questions 2 and 3 are resolved). |
| Data (schema, statuses, `data/` files) | None. No migration, no status change, nothing new in `data/`. Config: `scan.max_new_jobs_per_run` is removed (and rejected if present) and `scan.max_page_actions_per_run` is added (default 80). `ScanSettings` forbids unknown keys. |
| CLI / dashboard | `jobbot scan`: the summary line gains `page actions: A/N`; `P pages` counts every result-page load; the `Stopped early` text changes; a date-sorted search that ends early prints one line. No flag changes. A bad cap value, the old key or a misspelt `scan.` key exits 1 with a clear message instead of a traceback or a silent default. Nothing in the repo parses the summary text. No dashboard yet. |
| Prompts / decision schema | None. No `jobbot eval` run needed. |
| Safety rules | **Account protection (rule 3) is tightened, not weakened.** The per-run cap now bounds every bot-initiated Indeed request: page loads, clicks, retries and reloads (OQ-5). The old key can no longer be silently ignored (OQ-3: rejected with a `ConfigError`). The safety docs that name the old key must be updated (section 8). |
| Other capabilities | None functionally. `job-store` API and `scan --decide` are unchanged. `config.py` is shared code (workflow section 3 escalation list). `jobbot login` loads one results page with `search_url(..., 0)` (`cli.py:268`); with page index 0 there is no `start`, so login is unaffected. |

## 5. Acceptance criteria

New test files proposed: `tests/test_indeed_scanner.py` (scanner loop with a **fake page** that
serves synthetic results HTML per `start` value and records every `goto` and click, a real
`JobStore` on `tmp_path`, and `human_pause` / `time.sleep` patched to no-ops), and
`tests/test_config.py` (settings files written to `tmp_path`). No test opens a browser.

**AC-C1: New setting.** `ScanSettings` has `max_page_actions_per_run` with default **80** (OQ-2),
and no longer has `max_new_jobs_per_run`. Loading a `settings.yaml` with
`scan: {max_page_actions_per_run: 7}` gives 7; with no `scan` section, or no settings file, it
gives 80.
Verified by: unit test in `tests/test_config.py`.

**AC-C2: Invalid value.** `max_page_actions_per_run` set to `0`, `-1` or `abc` makes `load_settings`
raise `ConfigError` whose message names `scan.max_page_actions_per_run` and the settings file.
`jobbot scan` prints it and exits 1 without opening the browser. An invalid value in another
section (e.g. `llm.timeout_s: abc`) also raises `ConfigError` naming that dotted key (no pydantic
traceback).
Verified by: unit tests in `tests/test_config.py`, plus a Typer `CliRunner` test of `scan` with
`open_browser` patched to fail the test if it is called.

**AC-C3: Old key and misspelt keys are rejected (OQ-3, decided).** A `settings.yaml` containing
`scan.max_new_jobs_per_run` (with or without the new key) makes `load_settings` raise `ConfigError`
saying the key was renamed to `scan.max_page_actions_per_run`, that the new cap counts result-page
loads plus description reads, and to rename it in `config/settings.yaml`. A misspelt key under
`scan:` (e.g. `max_page_action_per_run`) raises `ConfigError` naming `scan.max_page_action_per_run`
as an unknown key. An unknown key in another section (e.g. `llm.foo: 1`) is still ignored
(unchanged). The old value is **never silently ignored**.
Verified by: unit tests in `tests/test_config.py`.

**AC-C4: Result-page loads are counted.** Every `goto` of a results URL adds 1 to the result-page
count and to `page_actions`, including a load that shows no cards. After any run,
`page_actions == result_page_loads + description_reads`, and `result_page_loads` equals the number
of results `goto` calls the fake page recorded.
Verified by: unit test in `tests/test_indeed_scanner.py` (one search with a full page, then an
empty page).

**AC-C5: Description reads are counted.** Each description attempt adds 1 to `description_reads`
and to `page_actions`, whether it succeeds, fails (no pane text), opens a full `/viewjob` page
(the `go_back` is not counted separately), or reads a pane that was already open.
Verified by: unit test with a fake page whose cards succeed, fail, open `/viewjob`, and one that is
already open.

**AC-C6: The cap is a hard limit.** For a cap N and a fake site that needs more than N actions,
the fake page records exactly N actions (results `goto`s plus card clicks plus already-open reads),
never N+1. Cases: N=1 (page 1 loads, no card is clicked); N=3 with 5 cards needing descriptions
(1 load + 2 clicks); N larger than the work needed (all work done, no extra action).
Verified by: parametrised unit test in `tests/test_indeed_scanner.py`.

**AC-C7: Old rows count the same; finished rows cost nothing.** On a page listing one job already
stored without a description, one stored with a description, and one new job, the scanner makes
exactly 2 description reads (the stored-without-description job and the new job) and none for the
job that already has a description.
Verified by: unit test with a pre-seeded `JobStore`.

**AC-C8: Clean stop.** When the cap refuses an action: no further `goto`, click or `human_pause`
happens; `run` returns without raising; the listings of the page already loaded are all in the
store (new ones with status `new` and a NULL description); descriptions stored earlier in the run
are kept; `stats.stopped_early` names `scan.max_page_actions_per_run`, the cap, and the
result-page/description split.
Verified by: unit test (patched `human_pause` records calls; fake page records actions; store
queried afterwards).

**AC-C9: "Stopped early" only when something was refused.** A run whose work needs exactly N
actions with cap N ends with `stopped_early` unset. The same run with cap N-1 ends with it set.
This also holds when the cap is reached on the last page of the last search (today's reporting gap).
Verified by: unit test.

**AC-C10: CLI summary.** `jobbot scan` prints `Scan done: P pages, L listings, N new jobs,
D descriptions read, F failed, U duplicates | page actions: A/CAP | signed in: ...`, where `P`
counts every result-page load. When the cap refused an action it then prints
`Stopped early: reached scan.max_page_actions_per_run=CAP (P result pages, D description reads)`.
The exit code is 0, and with `--decide` the decide step still runs. (The exact wording may be
adjusted in the plan; the fields may not.)
Verified by: `CliRunner` test with `open_browser` and `IndeedScanner` patched to return set `ScanStats`, and `_run_decide` patched to record the call.

**AC-C11: Retries and reloads (OQ-5, decided).** A failed first description attempt followed by
the retry counts as 2 description reads; the results reload after a human wait counts as 1
result-page load. If the cap is reached between the first attempt and the reload or the retry, the
refused action is not made and the job keeps a NULL description. Polling during `wait_for_human`
adds nothing, however many polls it takes. A card that opens a full `/viewjob` page costs 1
description read (the `go_back` adds nothing).
Verified by: unit test with a fake page whose first click shows a challenge that clears after
several polls (fake clock for `wait_for_human`), plus the cap-between-attempts variant.

**AC-C12: Page step (pending real-scan verification, OQ-1).** `search_url(base, search, k)` sets
`start = k * PAGE_STEP` for `k > 0` and omits `start` for `k = 0`. `PAGE_STEP` is the named constant
holding the value verified on 2026-11-28. There is no literal page-size number left in
`scanner.py`.
Verified by: updated `tests/test_indeed_parse.py::test_search_url` asserting `start={2*PAGE_STEP}`
for page index 2, plus a test pinning `PAGE_STEP` to the verified value (its comment points to the
observation note), so any later change is deliberate.

**AC-C13: Last page (pending real-scan verification, OQ-1).** Paging for a search continues after a
page with exactly `FULL_PAGE_SIZE` distinct listings (if `max_pages` allows) and stops after a page
with fewer. No further `goto` is made for that search.
Verified by: unit test with a fake site serving `FULL_PAGE_SIZE`, then `FULL_PAGE_SIZE - 1`
listings, and `max_pages: 3`; the fake page records exactly 2 results loads for that search.

**AC-C14: Page limits unchanged.** `--pages` (or `max_pages`) still bounds pages per search. A page
with no cards within the wait ends that search's paging, counts as one page action, and the scan
moves on to the next search.
Verified by: unit test (fake page returns no cards for page 2 of search A; search B is still loaded).

**AC-C15: Config and docs agree.** After the change, a search for `max_new_jobs_per_run` finds it
only in history (`changelog.md` entries, this change folder, and the OQ-3 error message and its
test). `config/settings.example.yaml` documents `max_page_actions_per_run` with its default and
meaning. `config/searches.yaml` states the verified jobs per page. The indeed-scanner spec (BR-8,
BR-9, AC-1, AC-15, AC-16, AC-19, section 11), `architecture/security.md` T-4,
`.claude/rules/indeed.md` and `CLAUDE.md` (with the developer's OK) say the same thing. The
real-scan results are recorded with a date in `documentation/customer/`.
Verified by: in `/review-feature`, run `rg max_new_jobs_per_run` and `rg "15 jobs|RESULTS_PER_PAGE"`
over the repo and read each file in section 8.

**AC-C16: Real-browser check (manual).** With `scan.max_page_actions_per_run: 5` in
`config/settings.yaml`, `jobbot scan -s <one search>` makes at most 5 visible page loads and card
clicks in the Chrome window, prints `page actions: 5/5`, and prints the `Stopped early` line if more
work was left.
Verified by: manual run by the developer, result recorded in `review.md` (fake-page tests cannot
prove the real Playwright flow).

**AC-C17: Early stop for date-sorted searches (OQ-4, decided).** For a `sort: date` search whose
page 1 has no new listings and none needing a description (all already stored with a description),
the fake page records exactly 1 results load for that search, the scan moves on to the next
search, and one line says the rest of that search was skipped. A `sort: relevance` search with the
same data still loads up to `max_pages`. A `sort: date` page that has at least one new listing, or
one stored listing still without a description, does not stop paging.
Verified by: unit test in `tests/test_indeed_scanner.py` with a pre-seeded `JobStore`.

**AC-C18: Actions after a skipped item still count.** With the `failure-screenshots` behaviour in
place (skip the item and carry on after a `wait_for_human` timeout): when the wait times out during
a description read, the next card's read counts as 1 description read; when it times out on a
results page, the next results load counts as 1 result-page load. The cap still refuses the
action that would exceed it, and `page_actions == result_page_loads + description_reads` holds.
Verified by: unit test in `tests/test_indeed_scanner.py` with `wait_for_human` patched to raise
`HumanActionTimeout` once (written against `failure-screenshots` as built).

Spec ACs replaced or changed: AC-1 becomes AC-C12; AC-15 is replaced by AC-C4 to AC-C9 and
AC-C18; AC-16 becomes AC-C13, AC-C14 and AC-C17; AC-19 is updated by AC-C10. The as-built gap "no automated test" for
AC-15 and AC-16 is closed by these tests (M-002, M-004).

## 6. Migration and compatibility

- **`data/jobs.db`:** no schema or status change, no migration. Jobs left with a NULL description by
  a capped run are read on a later run, as today.
- **Cached resume profiles, `decisions.jsonl`:** not affected.
- **`config/settings.yaml` (gitignored, the developer's copy):** on 2026-11-27 no such file
  existed in the working tree (only its existence was checked; Claude does not read that file).
  If one is created before this ships (e.g. copied from the old example), and it contains
  `max_new_jobs_per_run`, every `jobbot` command that loads settings fails with the rename message
  (OQ-3, AC-C3) until the line is changed to `max_page_actions_per_run: <number>`. Nothing is
  silently ignored.
- **`config/settings.example.yaml`, `config/searches.yaml`:** updated in the same change.
- **Tests:** `tests/test_indeed_parse.py:98` changes from a literal `start=20` to `2*PAGE_STEP`.
  The existing fixture stays.

## 7. Open questions and assumptions

Decided (2026-11-27, developer in chat): option (c), one cap on every Indeed page action, renamed
from `scan.max_new_jobs_per_run`, clean stop with a report. Recorded in `request.md`.

Also decided (2026-11-27, developer in chat), recorded in `request.md`:
- **OQ-2:** default 80.
- **OQ-3:** reject the old key with a clear `ConfigError`; `ScanSettings` gets `extra="forbid"`;
  `load_settings` turns `ValidationError` into `ConfigError`.
- **OQ-4:** yes, stop paging early, for `sort: date` searches only (BR-C7, AC-C17).
- **OQ-5:** retries and reloads count; polling during `wait_for_human` does not; the `go_back`
  after `/viewjob` is part of the same read.

Still open: **OQ-1** (blocked until the real scan on 2026-11-28).

**OQ-1: Real page size and `start` step. BLOCKED until the developer's real scan on 2026-11-28.**
How many cards does a full `in.indeed.com` results page show, and does `start` step by 10 or 15?
Does `start=10` overlap page 1? AC-C12 and AC-C13 are written in terms of `PAGE_STEP` and
`FULL_PAGE_SIZE` and stay "pending real-scan verification" until then.
*Recommendation:* use whatever step Indeed's **own** "Next" link uses, not a guessed one. If page
size and step differ, keep two constants (as in BR-C5).

Checklist for the real scan (passive observation only; solve any check by hand as usual):
- [ ] Note whether you are signed in, and the date.
- [ ] On page 1 of a broad search (e.g. `software engineer`, `India`), count the job cards and how
      many are marked "Sponsored". Optionally, in DevTools console:
      `window.mosaic.providerData["mosaic-provider-jobcards"].metaData.mosaicProviderJobCardsModel.results.length`
      (reading only).
- [ ] Click Indeed's own "Next" / "2" link and note the `start=` value in the address bar.
- [ ] Compare page 2 with page 1: does any job repeat (same title and company, or the same `vjk=`
      when you open it)? How many?
- [ ] If Indeed's step was not 10: (optional, one extra load) open `start=10` by hand and note
      whether it overlaps page 1.
- [ ] On a narrow search with few results, look at the last page: how many cards, and does a "Next"
      link still show? (Optional) what does a `start` past the end return: empty, the last page
      again, or a redirect?
- [ ] Note whether a "Verify you are human" check appeared, and after roughly how many page loads
      and clicks (input for OQ-2).
- [ ] Optional: save one full results page as a new fixture, trimmed and scrubbed of personal data
      (a signed-in page can show your name or email in the header).
- [ ] Record the results with the date in `documentation/customer/indeed-observations.md`.

**OQ-2: Default for `scan.max_page_actions_per_run`.** **Decided (developer in chat, 2026-11-27):
80.**
*Recommendation was: 80* (the same number as today, with a stricter meaning). Reasoning:
- With the default searches (7 x 2 pages = 14 result-page loads), 80 leaves about 66 description
  reads per run. Today's code allows 80 successful reads **plus** up to 14 loads **plus** all failed
  attempts, so 80 actions is never more Indeed traffic than today.
- A daily run with `fromage: 3` mostly sees known jobs, so a few dozen new descriptions fit easily.
- The first run on an empty DB (up to ~14 pages x 10-15 cards) needs 2 to 3 runs to read every
  description. That is fine, because unread jobs are kept and read later (BR-6).
- Lower (e.g. 50-60) if the real scan shows Cloudflare checks early in a run. Higher is not
  recommended until runs have been seen to pass without checks.

**OQ-3: The old key in an existing `settings.yaml`.** **Decided (developer in chat, 2026-11-27):
reject with a clear `ConfigError` telling the user to rename it; `extra="forbid"` on
`ScanSettings` only; `ValidationError` becomes `ConfigError` in `load_settings`** (BR-C6, AC-C2,
AC-C3). Today unknown keys are silently ignored
(`config.py:65-69`, pydantic default `extra="ignore"`), and pydantic errors are not turned into
`ConfigError` (`config.py:131-133`).
*Recommendation: reject with a clear `ConfigError`* (not an alias):
- the meaning changed, so the developer should choose the number again on purpose;
- it is a one-user tool, so the cost is one edit;
- there is no alias code to remove later.

Also recommended: set `extra="forbid"` on `ScanSettings`, so a typo in this safety key (e.g.
`max_page_action_per_run`) also fails loudly instead of falling back to the default, and turn
pydantic `ValidationError` in `load_settings` into `ConfigError` with the field path.
*Alternative:* accept the old key as a deprecated alias with a warning. This is safe because the
same number is now stricter, but it keeps an alias in the code.

**OQ-4: Stop paging a search early when a page has nothing new?** **Decided (developer in chat,
2026-11-27): yes, for `sort: date` searches only** (BR-C7, AC-C17).
*Recommendation was: yes, for `sort: date` searches only.* If a loaded page gives 0 new listings and 0
listings that still need a description, load no more pages of that search. Page loads now count
against the cap, so this saves actions for the searches that come later. It also covers Indeed
returning the last page again for a `start` past the end. For `sort: relevance`, later pages can
still hold new jobs, so don't stop early.
Accepted, so AC-C17 was added in section 5.

**OQ-5: Do `wait_for_human` retries and reloads count as actions?** **Decided (developer in chat,
2026-11-27): yes; polling while waiting does not count; the `go_back` after `/viewjob` is part of
the same read** (BR-C1, AC-C11). Related decision in `failure-screenshots`: after a
`wait_for_human` timeout the scanner skips the item and carries on, and every action after the
skip counts (AC-C18).
*Recommendation was: yes,* as written in BR-C1 and AC-C11. The second description attempt and the
results reload after a human wait are real requests that Indeed sees. The cap's job is to bound
that traffic, and "every `goto` and every click counts" is the simplest rule to test. The polling
inside `wait_for_human` is not counted, because it makes no request.
Also confirm: the `go_back` after a `/viewjob` page is part of the same description read (not
counted separately).

Assumptions:
- The cap is **per `jobbot scan` run**, shared by all searches in config order. There is still no
  daily scan cap (spec open question 6, out of scope).
- `jobbot login` is a separate command and is not limited by this cap.
- The paging constants are Indeed facts, not user settings (they belong in `parse.py`).
- No CLI flag to override the cap is wanted (not requested).

Blocking: OQ-2 to OQ-5 are decided, so planning can go ahead. **OQ-1 still blocks the values of
`PAGE_STEP` / `FULL_PAGE_SIZE` (AC-C12, AC-C13).** The plan names them and has a step to set them
from the real-scan checklist, but **plan approval should wait until the real scan has filled them
in**.

## 8. Files that must change together (consistency)

| File | Change |
|---|---|
| `src/jobbot/config.py:65-70` | `ScanSettings`: new key (default 80), old key removed, validation (`ge=1`), `extra="forbid"`. `load_settings` (`config.py:131-133`): `ValidationError` becomes `ConfigError`, with the rename message for the old key (OQ-3) |
| `src/jobbot/platforms/indeed/scanner.py` | Remove `RESULTS_PER_PAGE_STEP` (`:25`). Count actions in `run` / `_load_results` / `_read_description` / `_click_and_read`. Replace `_cap_reached` (`:138-139`). `ScanStats` (`:29-39`) gains page-action counts. Stop without the pause at `:84`. `stopped_early` per BR-C4 |
| `src/jobbot/platforms/indeed/parse.py:20-32` | `PAGE_STEP`, `FULL_PAGE_SIZE` with the verified values and date |
| `src/jobbot/cli.py:343-352` | Summary line and `Stopped early` text (AC-C10) |
| `tests/test_indeed_parse.py:95-98` | `test_search_url` uses `PAGE_STEP`; add the pinning test |
| `tests/test_indeed_scanner.py` (new, or extended if `failure-screenshots` created it first), `tests/test_config.py` (new) | AC-C1 to AC-C14, AC-C17, AC-C18 |
| `config/settings.example.yaml:26-30` | New key, default and meaning |
| `config/searches.yaml:5` | Verified jobs per page |
| `documentation/development/features/indeed-scanner/specification.md` | BR-8, BR-9, sections 5, 6, 9, AC-1, AC-15, AC-16, AC-19; resolve open questions 2 and 3 |
| `documentation/development/features/indeed-scanner/changelog.md` | Entry for this change |
| `documentation/development/features/indeed-scanner/implementation-plan.md` (as-built), section 3 | Config-key table and "hard-coded constants" note |
| `documentation/development/architecture/security.md:30` (T-4) | New key name and meaning |
| `documentation/development/architecture/data.md:88-89` | Check only: it lists no keys today, so probably no change |
| `.claude/rules/indeed.md:7` | New key name |
| `CLAUDE.md:105` ("Indeed scanning" notes) | New key name. Ask the developer before editing `CLAUDE.md` |
| `documentation/customer/indeed-observations.md` (new) | Real-scan results, dated (`.claude/rules/indeed.md`) |
| `.claude/mistakes/common-mistakes.md` M-004 | When the new tests guard both points, delete the entry and name the guard in the task report (log rules) |

No ADR is needed. This refines an existing control and makes no new architectural choice.

## 9. Risks

1. **Silent fallback to the default** if the old key is ignored after the rename (OQ-3). This is a
   safety risk if the developer had set a lower value. Mitigated by AC-C3 (rejected with a
   `ConfigError`, decided 2026-11-27). Side effect: a settings file with the old key stops every
   command until the key is renamed.
2. **Later searches get starved.** The cap is shared and searches run in config order. Now that
   page loads count, the cap is reached sooner, and the `remote-*` searches at the end may get no
   loads on busy days. This happened before as well, just later in a run. Mitigations (rotating the
   start search, per-search budgets) are out of scope. OQ-4 reduces wasted loads.
3. **Wrong paging constants.** A step larger than the page size skips jobs silently. A smaller step
   wastes counted actions on overlap. Mitigated by the real-scan check, the pinning test and the
   dated observation note. Indeed can change this later. An optional later guard: warn when a page's
   listings heavily overlap the previous page.
4. **Counting in the wrong place** (after the action instead of before) would allow N+1 actions.
   AC-C6 pins this.
5. **Fake-page fidelity.** Unit tests use a fake page, so the real Playwright flow (pane, `/viewjob`,
   blockers) is checked only by the manual AC-C16.
6. **First runs need more runs to back-fill descriptions** with a stricter cap. Expected and
   harmless (BR-6).
7. **Overlap with the parallel change `failure-screenshots`**, which also touches `scanner.py`.
   Order (in the plan): this change is built **after** `failure-screenshots` (and after
   `job-store/changes/llm-timeout-stops-run`), on top of its code, so its skip-and-carry-on paths
   are counted too (AC-C18).

## 10. Out of scope

- A daily scan cap (spec open question 6), and per-search budgets or rotating the search order.
- A CLI flag to override the cap.
- Changing the delays (BR-7), the timeouts or the `wait_for_human` flow.
- Page loads made by `jobbot login`.
- Failure screenshots (separate change `failure-screenshots`), company-size scraping, and
  back-filling descriptions for rows that no longer appear in results.
