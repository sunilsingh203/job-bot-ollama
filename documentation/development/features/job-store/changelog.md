# Changelog: job-store

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
