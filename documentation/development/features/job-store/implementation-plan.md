# Implementation plan: job-store

Status: As-built (retroactive).

Reconstructed on 2026-11-26 from the code at commit `c3677ba`. It describes what was built,
not a proposal. Spec: [specification.md](specification.md). The schema relocation is planned
separately in [changes/sql-migrations/](changes/sql-migrations/).

---

## 1. Affected layers

| Layer | Impact |
|---|---|
| DB | New SQLite database `data/jobs.db` with one table, `jobs` (details in section 2). |
| Persistence code | `src/jobbot/db.py`: `JobStore` (connection, writes, reads), `status_for`, `row_to_job`, `row_decision`. |
| Pipeline | `src/jobbot/pipeline.py`: `decide_pending`, `DecideStats`, the `OnDecision` progress callback. |
| CLI | `src/jobbot/cli.py`: `decide` (`--limit`, `--retry-failed`), `jobs` (`--status`, `--limit`), `show ID`, `_run_decide` (shared with `scan --decide`), `_store`, `STATUS_COLORS`. |
| Browser / Parsing | None directly. The indeed-scanner calls the store. |
| API / Frontend | None (CLI). The planned Streamlit dashboard will read `pending_review` rows. |
| Security | Local-only file under the gitignored `data/`; parameterised SQL everywhere except the `int()`-cast `LIMIT` in `to_decide`. |
| Tests | `tests/test_db_pipeline.py` (temporary-directory DB; a `FakeMatcher` stands in for the LLM). |
| Docs | CLAUDE.md "Job status lifecycle"; this folder. |

## 2. Database changes (explicit)

**Migration file:** `src/jobbot/migrations/0001_init.sql`, applied by `PRAGMA user_version`
(created by the sql-migrations change, ADR-0003). At commit `c3677ba` the same DDL was inline
in `src/jobbot/db.py` (`_SCHEMA`, lines 21-53) and ran on every `JobStore` open with
`CREATE ... IF NOT EXISTS`, followed by `PRAGMA user_version = 1`. From that change on, the
migration files are the only record of the schema.

**Table `jobs`** (new):

| Column | Type | Null / default |
|---|---|---|
| `id` | INTEGER | PRIMARY KEY |
| `platform` | TEXT | NOT NULL |
| `job_key` | TEXT | NOT NULL |
| `url` | TEXT | nullable |
| `title` | TEXT | NOT NULL DEFAULT '' |
| `company` | TEXT | NOT NULL DEFAULT '' |
| `location` | TEXT | NOT NULL DEFAULT '' |
| `description` | TEXT | nullable |
| `description_sha256` | TEXT | nullable |
| `snippet` | TEXT | nullable |
| `salary` | TEXT | nullable |
| `posted_at` | TEXT | nullable |
| `easy_apply` | INTEGER | nullable (0/1) |
| `remote` | INTEGER | nullable (0/1) |
| `company_size` | TEXT | nullable |
| `search_name` | TEXT | nullable |
| `status` | TEXT | NOT NULL DEFAULT 'new' |
| `decision` | TEXT | nullable |
| `resume_id` | TEXT | nullable |
| `score` | INTEGER | nullable |
| `reason` | TEXT | nullable |
| `decision_json` | TEXT | nullable |
| `error` | TEXT | nullable |
| `first_seen_at` | TEXT | NOT NULL |
| `updated_at` | TEXT | NOT NULL |
| `decided_at` | TEXT | nullable |

**Constraints:** `UNIQUE (platform, job_key)`. No foreign keys and no CHECK constraints (status values are not constrained).

**Indexes:**
- `idx_jobs_status ON jobs (status)`: for `to_decide`, `list_jobs(status)` and `counts`.
- `idx_jobs_desc ON jobs (description_sha256)`: for the duplicate lookup in `set_description`.
- (Implicit) the unique index for `(platform, job_key)`: for `get_by_key`.

**Schema version:** `PRAGMA user_version = 1`.

Destructive changes: none (this is the initial schema).

## 3. File / module map

| File | Responsibility | Key symbols (line numbers at c3677ba) |
|---|---|---|
| `src/jobbot/db.py` | SQLite store | `SCHEMA_VERSION` (L19), `_SCHEMA` (L21-53; moves to migrations), `UNDECIDED` (L56, unused), `status_for` (L63), `JobStore.__init__` (L72), `upsert_listing` (L92), `set_description` (L135), `save_decision` (L153), `mark_failed` (L178), `reset_failed` (L185), `get` (L196), `get_by_key` (L199), `needs_description` (L204), `to_decide` (L208), `list_jobs` (L217), `counts` (L229), `row_to_job` (L234), `row_decision` (L251) |
| `src/jobbot/migrations/0001_init.sql` | Schema DDL (from the sql-migrations change) | — |
| `src/jobbot/pipeline.py` | Decide loop | `DecideStats` (L17), `decide_pending` (L25) |
| `src/jobbot/cli.py` | Commands | `STATUS_COLORS` (L242), `_store` (L253), `decide_cmd` (L357), `_run_decide` (L370), `jobs` (L400), `show` (L436), `_build_matcher` (L116) |
| `src/jobbot/models.py` | `Job`, `Decision` | `Job.description_sha256` |
| `src/jobbot/llm/client.py` | Exception contract | `LLMError`, `LLMUnavailable(LLMError)` |
| `src/jobbot/matcher/decide.py` | `Matcher.decide` (called by the pipeline) | — |

## 4. Config keys used

| Key | Default | Used for |
|---|---|---|
| `data_dir` | `data` (project-relative) | DB path `data_dir/jobs.db` |
| `llm.model` (or `jobbot --model X`) | `gpt-oss:20b` | Printed by `_run_decide`; used by the matcher |
| `llm.timeout_s` | 600 | Indirect: an Ollama timeout stops the decide run (since 2026-11-27, changes/llm-timeout-stops-run; before that it became a per-job `failed`) |
| CLI `decide --limit` | none | Max jobs per decide run |
| CLI `jobs --limit` | 30 | Max rows listed (the store default is 50) |

The matcher's own keys (`matching.*`, `llm.*`) are documented by the resume-matcher capability.

## 5. Test plan (AC -> tests)

Run on 2026-11-26: `.venv\Scripts\python -m pytest -q tests/test_indeed_parse.py tests/test_db_pipeline.py` gave **18 passed** (12 of them in `tests/test_db_pipeline.py`, counting the 5 parametrised `test_status_for` cases).

| AC | Test | Status |
|---|---|---|
| AC-1 Store creation | `tests/test_db_pipeline.py::test_upsert_is_idempotent` (via the fixture) | Partial (`user_version`, indexes and reopen not asserted) |
| AC-2 Insert new listing | `tests/test_db_pipeline.py::test_upsert_is_idempotent` | Covered |
| AC-3 Idempotent upsert | `tests/test_db_pipeline.py::test_upsert_is_idempotent` | Covered |
| AC-4 Re-seen jobs keep state | `tests/test_db_pipeline.py::test_upsert_keeps_decision_and_status` | Partial (COALESCE refresh untested) |
| AC-5 Required keys | — | **Gap** |
| AC-6 Duplicate detection | `tests/test_db_pipeline.py::test_duplicate_descriptions` | Covered (error text not asserted) |
| AC-7 Decide queue | `tests/test_db_pipeline.py::test_jobs_without_description_are_not_decided`, `::test_duplicate_descriptions` | Partial (`limit` untested) |
| AC-8 Status mapping | `tests/test_db_pipeline.py::test_status_for` (5 cases) | Covered |
| AC-9 Save decision | `tests/test_db_pipeline.py::test_decide_pending_sets_statuses` | Partial |
| AC-10 Per-job failure | `tests/test_db_pipeline.py::test_decide_pending_sets_statuses` | Covered |
| AC-11 Abort on LLM unavailable | `tests/test_db_pipeline.py::test_decide_pending_aborts_when_llm_unavailable` | Covered |
| AC-12 Retry failed | `tests/test_db_pipeline.py::test_decide_pending_sets_statuses` | Partial (CLI flag untested) |
| AC-13 Decide limit | — | **Gap** |
| AC-14 Sequential processing | `tests/test_db_pipeline.py::test_decide_pending_aborts_when_llm_unavailable`, `::test_decide_pending_sets_statuses` | Covered |
| AC-15 Row to Job round-trip | `tests/test_db_pipeline.py::test_row_to_job_roundtrip` | Covered |
| AC-16 No-op decide | — | **Gap** (manual) |
| AC-17 Decide CLI output | — | **Gap** (manual) |
| AC-18 Jobs listing | — | **Gap** |
| AC-19 Show job | — | **Gap** (manual) |

Suggested future tests (not written): `ValueError` on a missing key; COALESCE refresh; `to_decide(limit)` and ordering; `list_jobs` ordering; `save_decision` `KeyError` + `decision_json`/`decided_at`; CLI tests with `typer.testing.CliRunner` against a temporary `data_dir`; migration tests (owned by sql-migrations).

## 6. Implementation steps (reconstructed)

1. Add `Job.platform`, `job_key`, `easy_apply`, `remote`, `salary`, `posted_at` and `description_sha256` to `models.py` (shared with the matcher).
2. `db.py`: the inline schema (`jobs` table, unique key, two indexes), `JobStore` with a connection using `sqlite3.Row` and per-write commits.
3. Writes: `upsert_listing` (check-then-insert/update, COALESCE refresh), `set_description` (hash + duplicate lookup), `save_decision` with `status_for`, `mark_failed`, `reset_failed`.
4. Reads: `get`, `get_by_key`, `needs_description`, `to_decide`, `list_jobs`, `counts`, `row_to_job`, `row_decision`.
5. `pipeline.py`: `decide_pending`, with `LLMUnavailable` aborting the run and `LLMError` marking the job failed; the `DecideStats` and `on_decision` callback.
6. `cli.py`: `decide` (+ `--retry-failed`, `--limit`), `jobs`, `show`, and `scan --decide` reusing `_run_decide`.
7. `tests/test_db_pipeline.py`, with a `FakeMatcher` scripting results and exceptions per job key.
8. (2026-11-26, separate change) Move the schema to `src/jobbot/migrations/0001_init.sql`, versioned by `PRAGMA user_version`. See `changes/sql-migrations/`.

## 7. Risks

| Risk | Impact | Current mitigation | Notes |
|---|---|---|---|
| SQLite concurrency (scan + decide + future dashboard) | `database is locked` errors | Short transactions (a commit per write) | No WAL, no busy-timeout setting, no retry. Revisit before the Streamlit dashboard (Step 3). |
| No status-transition guards | Invalid lifecycle states, e.g. a decided job reset to `new` | Callers gate writes (`needs_description`, `to_decide`) | Important before adding `approved`/`applied`, which feed the approve-before-submit flow. |
| Overly broad duplicate rule | Legitimate jobs hidden as `duplicate` | Error text points to the original job id | See spec Open question 4. |
| ~~Timeouts treated as per-job failures~~ | A slow model fails many jobs one by one, each costing `llm.timeout_s` | `--retry-failed` | Resolved 2026-11-27 by changes/llm-timeout-stops-run (a timeout stops the run). See spec Open question 2. |
| Schema evolution | Old DBs can't be altered with `CREATE IF NOT EXISTS` | Fixed by migration files (ADR-0003) | — |
| Prompt version only inside JSON | Hard to compare prompt versions with SQL | `json_extract` possible | A migration could add columns. |
| Unbounded DB growth | A larger file and slower listings over months | Indexes on `status`, hash | No pruning or archiving. |
| Personal / scraped data on disk | Privacy if `data/` is shared | `data/` is gitignored | No encryption (acceptable for a local tool). |

## 8. Related ADRs

- `documentation/development/decisions/ADR-0003-sql-migration-files.md`: the schema lives in explicit SQL migration files versioned by `PRAGMA user_version`.
- `documentation/development/decisions/ADR-0004-human-approval-never-auto-submit.md`: why the lifecycle has `pending_review` -> `approved` -> ... -> `ready_to_submit` and `applied` is only set after the user clicks Submit.
- Candidate ADRs not yet written: "SQLite via stdlib `sqlite3` (no ORM)"; "Abort the run on LLMUnavailable, fail per job on LLMError".
