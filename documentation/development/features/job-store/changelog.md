# Changelog: job-store

## 2026-11-28: Review remediation (llm-timeout-stops-run)
- A timeout stop now prints `Stopped - LLM timed out: ...`. Ollama-down stops still print `Stopped - LLM unavailable: ...`. The label change was approved by the developer in chat.
- Tests: `scan --decide` timeout stop and the unavailable-label regression; LLM test helpers moved to `tests/llm_fakes.py`.
- See `changes/llm-timeout-stops-run/review.md` section 6.

## 2026-11-27: Ollama timeouts stop the decide run. See changes/llm-timeout-stops-run/.
- An Ollama timeout (connect, read, write or pool, on any attempt) now raises `LLMTimeout`, a subclass of `LLMUnavailable`, so `decide_pending` stops on the first timeout with no retry. The current and remaining jobs stay `new`; previously each timed-out job became `failed` and the run went on.
- The stop message names the model and `llm.timeout_s` and suggests a smaller model (`jobbot --model`) or a larger `llm.timeout_s`. A stopped run still exits 0.
- Invalid JSON after the retry still marks only that job `failed`. No schema, status or config change; `llm.timeout_s` stays 600.
- Spec: BR-9, BR-10, T-8, T-10, §9, AC-10, AC-11, AC-17 updated; open question 2 resolved. Tests: `tests/test_db_pipeline.py` (2 new), `tests/test_cli_llm_errors.py` (new).

## 2026-11-26: Schema moved to SQL migration files. See changes/sql-migrations/.
- The `jobs` table DDL moved from the `_SCHEMA` string in `src/jobbot/db.py` to `src/jobbot/migrations/0001_init.sql`, applied by `PRAGMA user_version` (same columns, unique key and indexes). From now on the migration files are the only record of the schema (ADR-0003).

## 2026-11-26: Documented as-built
- Added `specification.md` and `implementation-plan.md`, reconstructed from the code at commit `c3677ba` (retroactive; awaiting approver review).
- Recorded the open questions (prompt version only in `decision_json`, timeouts treated as per-job failures, broad duplicate rule, no transition guards, SQLite concurrency). No code changed.

## Initial implementation (commit c3677ba)
- SQLite `JobStore` (`src/jobbot/db.py`): `jobs` table with `UNIQUE (platform, job_key)` and indexes on `status` and `description_sha256`; upsert, description and duplicate detection, decision, failure and retry operations.
- Status lifecycle `new` -> `filtered_out | skipped | pending_review | manual | duplicate | failed` (`status_for`).
- `pipeline.decide_pending`: sequential decide loop; `LLMUnavailable` stops the run, `LLMError` marks one job `failed`.
- CLI: `jobbot decide [--limit N] [--retry-failed]`, `jobbot jobs [--status S] [--limit N]`, `jobbot show ID`, `jobbot scan --decide`.
- Tests: `tests/test_db_pipeline.py`.
