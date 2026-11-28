# Specification: job-store

Status: As-built — documented retroactively on 2026-11-26 from the existing code. Awaiting review by the approver (approval: by the developer, by hand or recorded from chat — ADR-0005).

Capability: a local SQLite store of every job the bot has seen (one row per platform job,
with its latest decision), the job status lifecycle, and the "decide over the DB" pipeline
(`decide_pending`) with its CLI commands (`jobbot decide`, `jobbot jobs`, `jobbot show`).

All file:line references are to commit `c3677ba`. From the change
[`changes/sql-migrations/`](changes/sql-migrations/) on, the schema DDL lives in
`src/jobbot/migrations/0001_init.sql` (applied by `PRAGMA user_version`) instead of the
`_SCHEMA` string in `src/jobbot/db.py`. The columns are the same. Rows changed by
[`changes/llm-timeout-stops-run/`](changes/llm-timeout-stops-run/) (2026-11-27: BR-9, BR-10,
T-8, T-10, §9, AC-10, AC-11, AC-17) reference the code after that change.

---

## 1. Purpose

Give every pipeline step one durable, local place to record jobs and where each one is in the
pipeline: the scanner writes listings and descriptions; the decide step reads undecided jobs,
asks the matcher (rule filters + local LLM), and stores the decision and the resulting status;
the user lists and inspects jobs from the CLI (and later from the review dashboard). The store
keeps re-scans idempotent, detects duplicate postings, and makes the decide step safe to stop
and resume (for example when Ollama is down or runs out of memory).

## 2. Actors

| Actor | Role |
|---|---|
| Developer / operator (single local user) | Runs `jobbot decide [--limit N] [--retry-failed]`, `jobbot jobs [--status S] [--limit N]`, `jobbot show ID`, `jobbot scan --decide`. Will approve or reject jobs in the planned dashboard. |
| The bot: scanner (`indeed-scanner`) | Inserts and refreshes listings, and stores descriptions. |
| The bot: pipeline (`decide_pending`) | Picks `new` jobs, calls the matcher, and stores decisions or failures. |
| Local LLM (Ollama, via the resume-matcher `Matcher`) | Produces apply/skip decisions. It can be unavailable or time out (raises `LLMUnavailable`; a timeout is its subclass `LLMTimeout`) or return a bad answer for one job (raises `LLMError`). |
| Indeed + Cloudflare | Indirect only: the source of the data written by the scanner. The job store makes no network calls. |

## 3. Scope

In scope:
- SQLite database `data/jobs.db` (`settings.data_dir / "jobs.db"`): the `jobs` table, its unique key and indexes.
- Writes: `upsert_listing`, `set_description` (with duplicate detection), `save_decision`, `mark_failed`, `reset_failed`.
- Reads: `get`, `get_by_key`, `needs_description`, `to_decide`, `list_jobs`, `counts`; helpers `row_to_job`, `row_decision`.
- `status_for`: mapping a matcher `Decision` + the `easy_apply` flag to a status.
- `pipeline.decide_pending`: a sequential decide loop with abort and failure semantics.
- CLI: `jobbot decide`, `jobbot jobs`, `jobbot show`, and the decide part of `jobbot scan --decide`.

Out of scope:
- How the decision is made (rule filters, company type, LLM prompt, resume selection): the resume-matcher capability (`src/jobbot/matcher/`).
- Writing `data/decisions.jsonl` (done by `Matcher._log`, not by the store).
- Statuses after review (`approved`, `rejected`, `filling`, `ready_to_submit`, `applied`): **planned** for Steps 3–4. They are listed in the `db.py` docstring only; no code sets them.
- Multi-user access, a server database, remote sync, backups.
- Migration mechanics: owned by `changes/sql-migrations/` (ADR-0003).

## 4. Business rules

| ID | Rule | Where |
|---|---|---|
| BR-1 | One row per platform job: `UNIQUE (platform, job_key)`. Both are required to upsert (`ValueError` otherwise). | `db.py:49`, `db.py:97-98` |
| BR-2 | Upserting an existing job never changes its status, description or decision. Only `easy_apply` and `salary` are refreshed (when the new value is not NULL, via `COALESCE`), plus `updated_at`. | `db.py:100-108` |
| BR-3 | New jobs start as `new` with a NULL description, `first_seen_at = updated_at = now`. | `db.py:109-133`, schema default |
| BR-4 | Storing a description computes `sha256(description UTF-8)`. If **any other** row already has the same hash, the job becomes `duplicate` with `error = "Same description as job #<id>"`; otherwise it becomes (or stays) `new`, with `error = NULL`. The match is exact (on the text after `html_to_text`/`normalize`), across all platforms and statuses. | `db.py:135-151`, `models.py:25-27` |
| BR-5 | Only jobs with `status = 'new'` **and** a non-NULL description are decided, oldest first (`first_seen_at`, then `id`), optionally capped by `--limit`. | `db.py:208-215` |
| BR-6 | `status_for(decision, easy_apply)`: `stage == "filter"` -> `filtered_out`; else `decision == "skip"` -> `skipped`; else (`apply`) `pending_review` if `easy_apply` is true, otherwise `manual` (including `easy_apply` NULL/unknown). | `db.py:63-68` |
| BR-7 | Saving a decision sets `status`, `decision`, `resume_id`, `score`, `reason`, `decision_json` (the full `Decision`, including `role_track`, `company_type`, `notes`, `model`, `prompt_version`, `latency_s`), clears `error`, and sets `decided_at` and `updated_at`. | `db.py:153-176` |
| BR-8 | Jobs are decided one at a time, sequentially (no parallel LLM calls). | `pipeline.py:39-58` |
| BR-9 | If the LLM is unavailable or a call **times out** (`LLMUnavailable`: Ollama unreachable, a non-200 HTTP response such as an out-of-memory error, or an httpx timeout of any kind (connect, read, write, pool) on any attempt of the call, raised as its subclass `LLMTimeout`), the run **stops immediately**. There is **no retry** after a timeout. The current and all remaining jobs stay `new` (no row is written for the current job) and are picked up by the next run. The timeout message names the model, the configured `llm.timeout_s` and a hint (a smaller model via `jobbot --model`, or a larger `llm.timeout_s`). Changed 2026-11-27 (changes/llm-timeout-stops-run): timeouts used to be per-job failures. | `pipeline.py:44-46`, `llm/client.py:108-131` (`LLMTimeout`: 116-124) |
| BR-10 | A per-job `LLMError` that is not an `LLMUnavailable` (today: invalid JSON after 2 attempts) marks only that job `failed` (with the error text truncated to 1,000 chars) and the run continues. Timeouts are not in this group (BR-9). | `pipeline.py:47-53`, `db.py:178-183`, `llm/client.py:106` |
| BR-11 | `--retry-failed` puts **all** `failed` jobs back to `new` (clearing `error`) before deciding. | `db.py:185-192`, `cli.py:365-366` |
| BR-12 | Every write commits immediately (autocommit per operation), so an interrupted run keeps everything done so far. | `db.py` |
| BR-13 | The store never deletes rows. | `db.py` |

## 5. Data entities

### `jobs` table (SQLite; `src/jobbot/db.py:21-53`, from the migrations change on `src/jobbot/migrations/0001_init.sql`)

| Column | Type / constraint | Written by | Meaning |
|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY` | SQLite | Local job id (shown by `jobbot jobs`, used by `jobbot show ID`). |
| `platform` | `TEXT NOT NULL` | `upsert_listing` | Platform name, e.g. `indeed`. |
| `job_key` | `TEXT NOT NULL` | `upsert_listing` | The platform's job id (Indeed `jk`). |
| `url` | `TEXT` | `upsert_listing` | Job URL (`{base}/viewjob?jk=...`). |
| `title` | `TEXT NOT NULL DEFAULT ''` | `upsert_listing` | Job title (first-seen value). |
| `company` | `TEXT NOT NULL DEFAULT ''` | `upsert_listing` | Company name (first-seen value). |
| `location` | `TEXT NOT NULL DEFAULT ''` | `upsert_listing` | Formatted location (first-seen value). |
| `description` | `TEXT` | `set_description` | Full job description as plain text; NULL until read. |
| `description_sha256` | `TEXT` | `set_description` | Hex SHA-256 of `description`; used for duplicate detection. |
| `snippet` | `TEXT` | `upsert_listing` | Search-result snippet as plain text. |
| `salary` | `TEXT` | `upsert_listing` (insert + refresh) | Salary text as shown by Indeed. |
| `posted_at` | `TEXT` | `upsert_listing` | ISO date (UTC) of posting. |
| `easy_apply` | `INTEGER` (0/1/NULL) | `upsert_listing` (insert + refresh) | Indeed "Easily apply". NULL = unknown. |
| `remote` | `INTEGER` (0/1/NULL) | `upsert_listing` | Remote flag. |
| `company_size` | `TEXT` | `upsert_listing` | Company size text; currently always NULL from the scanner. |
| `search_name` | `TEXT` | `upsert_listing` | Name of the search that **first** found the job. |
| `status` | `TEXT NOT NULL DEFAULT 'new'` | several | Lifecycle status (section 6). No CHECK constraint. |
| `decision` | `TEXT` | `save_decision` | `apply` or `skip`. |
| `resume_id` | `TEXT` | `save_decision` | Chosen resume id (only for apply). |
| `score` | `INTEGER` | `save_decision` | LLM score 0–100 (NULL for filter decisions). |
| `reason` | `TEXT` | `save_decision` | Short explanation. |
| `decision_json` | `TEXT` | `save_decision` | Full `Decision` model as JSON (includes `stage`, `role_track`, `company_type`, `company_type_source`, `notes`, `required_experience_years`, `model`, `prompt_version`, `latency_s`). |
| `error` | `TEXT` | `set_description`, `mark_failed`, cleared by `save_decision` / `reset_failed` | Duplicate note or LLM error text (max 1,000 chars from `mark_failed`). |
| `first_seen_at` | `TEXT NOT NULL` | `upsert_listing` | Local time, ISO 8601, seconds, no timezone. |
| `updated_at` | `TEXT NOT NULL` | every write | Local time, ISO 8601. |
| `decided_at` | `TEXT` | `save_decision` | Local time of the last decision. |

Constraints and indexes:
- `UNIQUE (platform, job_key)` (implicit unique index).
- `idx_jobs_status ON jobs (status)`.
- `idx_jobs_desc ON jobs (description_sha256)`.
- `PRAGMA user_version = 1` (`SCHEMA_VERSION`). At c3677ba it is set unconditionally after `CREATE TABLE IF NOT EXISTS`; from the migrations change on, it drives which migration files are applied.

### Related in-memory models
- `Job` (`src/jobbot/models.py`): converted from a row by `row_to_job` (booleans restored from 0/1/NULL).
- `Decision` (`src/jobbot/models.py`): input to `save_decision` / `status_for`; restored as a dict by `row_decision`.
- `DecideStats` (`pipeline.py:17-22`): `decided`, `failed`, `by_status` (Counter), `aborted` (error text when the LLM became unavailable).

## 6. States and transitions

Statuses: `new`, `filtered_out`, `skipped`, `pending_review`, `manual`, `duplicate`, `failed`
(implemented); `approved`, `rejected`, `filling`, `ready_to_submit`, `applied` (**planned**,
not implemented).

| # | From | To | Trigger | Implemented? | Where |
|---|---|---|---|---|---|
| T-1 | (none) | `new` | `upsert_listing` of an unseen `(platform, job_key)` | Yes | `db.py:109-133` |
| T-2 | `new` (no description) | `new` | `set_description`, unique hash | Yes | `db.py:135-151` |
| T-3 | `new` (no description) | `duplicate` | `set_description`, hash equals another row's | Yes | `db.py:135-151` |
| T-4 | `new` | `filtered_out` | `save_decision` with `stage="filter"` | Yes | `db.py:63-68` |
| T-5 | `new` | `skipped` | `save_decision`, LLM `skip` | Yes | same |
| T-6 | `new` | `pending_review` | `save_decision`, `apply` + `easy_apply` true | Yes | same |
| T-7 | `new` | `manual` | `save_decision`, `apply` + `easy_apply` false/unknown | Yes | same |
| T-8 | `new` | `failed` | `mark_failed` after a per-job `LLMError` that is not an `LLMUnavailable` (invalid JSON after the retry; not a timeout) | Yes | `pipeline.py:47-53` |
| T-9 | `failed` | `new` | `reset_failed` (`jobbot decide --retry-failed`) | Yes | `db.py:185-192` |
| T-10 | `new` | `new` | `LLMUnavailable`, including a timeout (`LLMTimeout`): run aborted, job untouched | Yes | `pipeline.py:44-46` |
| T-11 | any | same | `upsert_listing` of an existing job | Yes | `db.py:100-108` |
| T-12 | `pending_review` | `approved` / `rejected` | User review in the dashboard | **Planned** (Step 3) | — |
| T-13 | `approved` | `filling` -> `ready_to_submit` | Form filler fills and stops before Submit | **Planned** (Step 4) | — |
| T-14 | `ready_to_submit` | `applied` | The user clicks Submit; the bot detects confirmation | **Planned** (Step 4) | — |

Transition enforcement: **none in code or DB.** Write methods do not check the current status
(e.g. `save_decision` works on a job in any status; `set_description` sets `new`/`duplicate`
regardless of the previous status). The transitions above hold because of how callers use the store
(`needs_description` gates `set_description`; `to_decide` gates `save_decision`/`mark_failed`).

## 7. Permissions & data scope

- Single local user. No authentication or roles; anyone who can run `jobbot` on the machine can read and change all rows.
- Data is local-only: `data/jobs.db` is under the gitignored `data/` directory. The store makes no network calls. The LLM it reaches through the matcher is the local Ollama server only.
- The DB holds job data scraped from Indeed and decision metadata. It holds no credentials and none of the user's profile facts (those stay in `profile.yaml`). The `reason`/`notes` text written by the LLM can still mention the user's experience.
- Indeed account protection is not affected by the store (no network), but `failed`/`duplicate` handling keeps re-scans from re-reading jobs already stored.
- Human approval: the store has no path that submits anything. Applying stays behind the planned `approved` -> `ready_to_submit` -> user-clicks-Submit flow (ADR-0004).

## 8. Validation rules

| ID | Rule | Where |
|---|---|---|
| V-1 | `upsert_listing` requires a non-empty `job.platform` and `job.job_key` (`ValueError`). | `db.py:97-98` |
| V-2 | `(platform, job_key)` must be unique (DB constraint; the code checks first and updates instead of inserting). | `db.py:49, 100` |
| V-3 | `save_decision` on an unknown id raises `KeyError`. | `db.py:154-156` |
| V-4 | `Decision` is a pydantic model (`decision` in `apply|skip`, `stage` in `filter|llm`, `company_type` in `startup|mnc|unknown`), validated before it reaches the store. | `models.py:30-43` |
| V-5 | `to_decide(limit)` casts `limit` with `int()` before putting it in the SQL text. | `db.py:213-214` |
| V-6 | `mark_failed` truncates the error to 1,000 characters. | `db.py:181` |
| V-7 | Not validated: `status` values (no CHECK constraint, and `jobbot jobs --status` accepts any string), status transitions, `score` range in the DB. | — |

## 9. Error cases

| Case | Behaviour | Where |
|---|---|---|
| Ollama unreachable / HTTP error (e.g. OOM at model load) during `decide` | Run stops; summary prints `Decided N (...)` then `Stopped - LLM unavailable: <msg>`; the remaining jobs stay `new`. | `pipeline.py:44-46`, `cli.py:394-397` |
| Ollama timeout while deciding job *i* (any attempt, including the retry after invalid JSON and the no-`think` retry) | Run stops at once, with no retry. Job *i* and later jobs stay `new` (error, decision and `decided_at` NULL); jobs 1..*i-1* keep their results. The CLI prints no `-> failed` line for job *i*, then `Decided N (...)` and `Stopped - LLM timed out: Ollama timed out after <timeout_s>s (model <model>). ...` with the hint (smaller model via `jobbot --model`, or a larger `llm.timeout_s`). Exit code 0, as for any stopped run. | `llm/client.py:116-124`, `pipeline.py:44-46`, `cli.py:394-397` |
| LLM unavailable or timed out while building resume profiles (before any job) | `_build_matcher` raises `LLMUnavailable` / `LLMTimeout` (both `LLMError`s) -> `Error: ...` exit 1 (a timeout message carries the hint); no job is touched. | `cli.py:388-393` |
| Bad JSON from the model (after 1 retry) for one job | That job becomes `failed` with the error; the CLI prints `[i/n] title @ company -> failed: <err>`; the run continues. | `pipeline.py:47-53`, `cli.py:379-381` |
| Other exceptions from the matcher (`ValueError`, incl. pydantic `ValidationError`, `ConfigError`) | Not caught by `decide_pending`; the CLI prints `Error: ...` exit 1. Jobs decided earlier stay saved; the current job stays `new`. | `cli.py:392-393` |
| No jobs to decide | `No new jobs to decide.`; the LLM is never contacted. | `cli.py:371-374` |
| `jobbot jobs` on an empty DB | `Database is empty. Run \`jobbot scan\` first.` | `cli.py:410-412` |
| `jobbot show ID` with an unknown id | `Error: No job with id ID`, exit 1. | `cli.py:442-443` |
| DB file locked by another process | `sqlite3.OperationalError: database is locked` after SQLite's default 5 s busy timeout (not handled). | — |
| `data/` missing | Created automatically (`mkdir(parents=True)`). | `db.py:73` |

## 10. Acceptance criteria (current behaviour)

**AC-1: Store creation.** Opening `JobStore(path)` creates the parent directory and the `jobs` table with its indexes if missing, sets `PRAGMA user_version` to 1, and can be reopened without error or data loss.
Verified by: tests/test_db_pipeline.py::test_upsert_is_idempotent (creation via the `store` fixture). Gap: `user_version`, the indexes and reopening an existing file are not asserted (manual: open `data/jobs.db` twice and run `PRAGMA user_version`). The concurrent sql-migrations change owns the migration-specific tests.

**AC-2: Insert new listing.** `upsert_listing` for an unseen `(platform, job_key)` inserts one row with `status='new'` and a NULL description, and returns `True`; `needs_description` is then true.
Verified by: tests/test_db_pipeline.py::test_upsert_is_idempotent

**AC-3: Idempotent upsert.** Upserting the same `(platform, job_key)` again returns `False` and does not add a row (status counts unchanged).
Verified by: tests/test_db_pipeline.py::test_upsert_is_idempotent

**AC-4: Re-seen jobs keep their state.** Upserting a job that already has a description and a decision keeps its `status`, `description` and decision columns.
Verified by: tests/test_db_pipeline.py::test_upsert_keeps_decision_and_status. Gap: the `COALESCE` refresh of `easy_apply`/`salary` (new non-NULL value wins, NULL keeps the old one) is not tested.

**AC-5: Required keys.** `upsert_listing` raises `ValueError` when `platform` or `job_key` is missing.
Gap: no automated test (manual: call it with `Job(description="")` in a REPL).

**AC-6: Duplicate detection.** `set_description` returns `new` for the first job with a given description text, and `duplicate` for a second job with byte-identical text. The duplicate row gets `error = "Same description as job #<first id>"` and is excluded from `to_decide`.
Verified by: tests/test_db_pipeline.py::test_duplicate_descriptions (the `error` text is not asserted).

**AC-7: Decide queue.** `to_decide()` returns only rows with `status='new'` and a non-NULL description, ordered by `first_seen_at` then `id`. `to_decide(n)` returns at most `n` rows.
Verified by: tests/test_db_pipeline.py::test_jobs_without_description_are_not_decided, tests/test_db_pipeline.py::test_duplicate_descriptions. Gap: `limit` is not tested.

**AC-8: Status mapping.** `status_for` returns `filtered_out` for a filter-stage decision, `skipped` for an LLM skip, `pending_review` for apply + `easy_apply=True`, and `manual` for apply + `easy_apply` False or None.
Verified by: tests/test_db_pipeline.py::test_status_for

**AC-9: Save decision.** `save_decision` stores status (via `status_for`), `decision`, `resume_id`, `score`, `reason`, `decision_json`, sets `decided_at`, clears `error`, and returns the status; an unknown id raises `KeyError`.
Verified by: tests/test_db_pipeline.py::test_decide_pending_sets_statuses (status, `resume_id`, `score`). Gap: `decision_json`, `decided_at`, error clearing and `KeyError` are not asserted.

**AC-10: Per-job failure.** In `decide_pending`, a job whose matcher call raises an `LLMError` that is not an `LLMUnavailable` (invalid JSON after the retry; not a timeout) is marked `failed` (error text stored), counted in `stats.failed` and `by_status["failed"]`, reported to `on_decision` with `decision=None`, and the loop continues with the next job.
Verified by: tests/test_db_pipeline.py::test_decide_pending_sets_statuses, tests/test_db_pipeline.py::test_decide_pending_marks_failed_on_client_invalid_json (the real client error)

**AC-11: Abort on LLM unavailable or timeout.** When the matcher raises `LLMUnavailable`, including a timeout (`LLMTimeout`), `decide_pending` stops at once (no further matcher calls, no retry), sets `stats.aborted` to the message, does not report the job to `on_decision`, and leaves that job and all remaining jobs `new` (error, decision and `decided_at` NULL), in the same `to_decide()` order for the next run. Jobs decided earlier keep their results. `jobbot decide` then prints `Decided N (...)` and a `Stopped` line with the timeout message and hint, prints no `-> failed` line, and exits 0. A timeout while building resume profiles prints `Error: <message>` and exits 1 with no job touched.
Verified by: tests/test_db_pipeline.py::test_decide_pending_aborts_when_llm_unavailable, tests/test_db_pipeline.py::test_decide_pending_stops_on_timeout, tests/test_cli_llm_errors.py::test_decide_stops_on_timeout_with_hint, tests/test_cli_llm_errors.py::test_decide_timeout_while_profiling_exits_1. `jobbot scan --decide` uses the same `_run_decide` (`cli.py:353-354`); checked by inspection (no browser in tests).

**AC-12: Retry failed.** `reset_failed()` sets every `failed` job back to `new` with `error` NULL and returns how many it reset; those jobs are then in `to_decide()`. `jobbot decide --retry-failed` prints `Re-queued N failed jobs.` before deciding.
Verified by: tests/test_db_pipeline.py::test_decide_pending_sets_statuses (store level). Gap: the CLI flag has no automated test.

**AC-13: Decide limit.** `jobbot decide --limit N` decides at most the N oldest eligible jobs.
Gap: no automated test (manual: with more than N `new` jobs, run `jobbot decide --limit 1`; exactly one changes status).

**AC-14: Sequential processing.** `decide_pending` calls the matcher for one job at a time, in `to_decide` order, and reports progress `(i, n, job, decision|None, status|error)` after each.
Verified by: tests/test_db_pipeline.py::test_decide_pending_aborts_when_llm_unavailable (call order) and tests/test_db_pipeline.py::test_decide_pending_sets_statuses.

**AC-15: Row to Job round-trip.** `row_to_job` rebuilds a `Job` with the description and with `easy_apply`/`remote` restored as `True`/`False`/`None`.
Verified by: tests/test_db_pipeline.py::test_row_to_job_roundtrip

**AC-16: No-op decide.** When no job is eligible, `jobbot decide` prints `No new jobs to decide.` and does not contact Ollama.
Gap: no automated test (manual: run `jobbot decide` with Ollama stopped on a fully decided DB).

**AC-17: Decide CLI output.** For each job `jobbot decide` prints `[i/n] title @ company -> <status> | score | resume_id` and the reason (or `-> failed: <error>`), then `Decided N (status: count, ...)`, plus `Stopped - LLM unavailable: ...` when aborted.
Partly verified by: tests/test_cli_llm_errors.py::test_decide_stops_on_timeout_with_hint (the `-> <status>` line, `Decided N (...)` and the `Stopped` line). Gap: the reason line and the `-> failed: <error>` line have no automated test.

**AC-18: Jobs listing.** `jobbot jobs [--status S] [--limit N=30]` prints the status counts and a table (id, status, score, resume, easy, title, company, location). With `--status`, rows are ordered by score (highest first), then most recently updated; without it, by most recently updated. An empty DB prints the "Database is empty" hint.
Gap: no automated test (`list_jobs`/`counts` are only exercised indirectly through `counts()` in tests/test_db_pipeline.py).

**AC-19: Show job.** `jobbot show ID` prints the title, company, location, status, easy apply, salary, posted date, URL, decision summary (decision, score, resume, company type and source, reason, notes), any error, and the full description (or `(no description yet)`). An unknown id gives `Error: No job with id ID` (exit 1).
Gap: no automated test (manual run).

## 11. Open questions & assumptions

Inconsistencies with CLAUDE.md / docs:
1. **Prompt version is not a column.** CLAUDE.md says to "store the prompt version with each decision in the DB, so prompt changes can be compared". It is stored only inside `decision_json` (as `model`, `prompt_version`, `latency_s`), so comparing needs `json_extract`. Decide whether to promote these to columns (it would need a migration).
2. ~~**Timeouts count as per-job failures.**~~ **Resolved 2026-11-27** by changes/llm-timeout-stops-run: an Ollama timeout now raises `LLMTimeout` (an `LLMUnavailable`) and stops the run on the first timeout (BR-9, T-10, AC-11). `llm.timeout_s` keeps its 600 s default. Jobs that became `failed` through a timeout in earlier runs stay `failed` until `jobbot decide --retry-failed`. A job that always times out would stop every run at the same place; this risk was accepted by the developer (revisit only if seen).
3. **"Already applied" filter.** The CLAUDE.md pipeline lists "already applied" as a rule filter, but there is no `applied` status yet and the filters don't query the DB. This depends on Step 4.
4. **Duplicate semantics.** A duplicate is any other row with an identical description hash, whatever its status or platform. Effects: (a) the same posting relisted under a new job key is never decided again, even when the original was `failed` or `filtered_out` for a reason that no longer applies; (b) the same JD for several locations keeps only the first location; (c) `reset_failed` does not re-check duplicates. Confirm.
5. **No transition guards and no CHECK constraint on `status`.** Invalid states are possible through direct calls (e.g. `set_description` on a decided job would reset it to `new`). Planned statuses will need guards (e.g. only `pending_review` -> `approved`), especially for the approve-before-submit flow.
6. **Existing jobs are only partly refreshed on upsert.** Title, company, location, snippet, `remote`, `posted_at` and `search_name` keep their first-seen values.
7. **Timestamps are naive local time** (`datetime.now()`), while `posted_at` is a UTC date.
8. **`jobbot show`** prints `easy apply: False` when `easy_apply` is NULL (unknown), while `jobbot jobs` prints `?`.
9. **`jobbot scan --decide`** runs the decide step even after the scan was interrupted with Ctrl+C or a human-wait timeout (see the indeed-scanner spec).

Risks:
10. **SQLite concurrency.** One connection per process, default rollback journal (no WAL), a commit per write, default 5 s busy timeout. Running `jobbot scan` and `jobbot decide` at the same time, or the planned Streamlit dashboard, can raise "database is locked". Not handled.
11. **Unbounded growth.** Rows and full descriptions are never pruned.
12. **Schema history.** At c3677ba the schema was implicit (`CREATE TABLE IF NOT EXISTS` + an unconditional `user_version=1`), so an existing DB could not have been altered. This is resolved by the sql-migrations change (ADR-0003).

Assumptions:
- A single user runs one jobbot command at a time.
- Job keys are stable per platform; description text from `html_to_text` is deterministic for the same page.

## 12. Dependencies

| Depends on | Why |
|---|---|
| resume-matcher (`src/jobbot/matcher/decide.py` `Matcher`, filters, company type, resume selection) | `decide_pending` calls `Matcher.decide(job)` for every queued job; `_build_matcher` in the CLI loads settings, `profile.yaml`, the resume library, cached profiles and the MNC list. |
| LLM client (`src/jobbot/llm/client.py`) | The `LLMError` / `LLMUnavailable` / `LLMTimeout` exception contract drives the failure/abort semantics (`LLMTimeout` is an `LLMUnavailable`, so a timeout stops the run). |
| `src/jobbot/models.py` | `Job`, `Decision`, `description_sha256`. |
| Config | `settings.data_dir` (DB location), `settings.llm.model` (printed). |
| SQLite (Python standard-library `sqlite3`) | Storage. |
| sql-migrations change (`changes/sql-migrations/`, ADR-0003) | Owns schema creation and versioning from 2026-11-26. |
| Used by | `indeed-scanner` (writes listings and descriptions); the planned review dashboard (Step 3) and form filler (Step 4). |
