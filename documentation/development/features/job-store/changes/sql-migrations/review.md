# Review: SQL migration files for the job store

- **Date:** 2026-11-26
- **Reviewer:** AI (self-review of its own implementation; a human review is still advised)
- **Inputs:** `change-definition.md` (AC-1..AC-11), `implementation-plan.md`
- **Approval:** developer, in chat, 2026-11-26 (no `plan-approval.md`; the approver may add one)

## Files changed

| File | Change |
|---|---|
| `src/jobbot/db.py` | Removed `_SCHEMA`. Added `MigrationError`, `Migration`, `load_migrations()`, `_check_sequence()`, `_user_version()`, `migrate()`; `SCHEMA_VERSION` derived from the files; `JobStore.__init__` calls `migrate()` and closes the connection if it fails. Public `JobStore` API unchanged. |
| `src/jobbot/migrations/__init__.py` | New. Docstring with the rules for migration authors. |
| `src/jobbot/migrations/0001_init.sql` | New. The `jobs` table + `idx_jobs_status` + `idx_jobs_desc`, verbatim from the old `_SCHEMA` (with `IF NOT EXISTS`), plus a header comment. |
| `tests/test_migrations.py` | New. 19 tests. |
| `pyproject.toml` | Not changed (hatchling already ships the `.sql` file, see AC-10). |

The real `data/jobs.db` was not opened or modified. Nothing was committed.

## Commands run (actual output)

| Command | Result |
|---|---|
| `.venv\Scripts\python -m pytest -q` (before the change) | `66 passed in 1.11s` |
| `.venv\Scripts\python -m pytest -q` (after) | `85 passed in 1.33s` (66 existing + 19 new) |
| `.venv\Scripts\python -m pytest -q tests/test_migrations.py` | `19 passed in 0.49s` |
| `.venv\Scripts\ruff check src tests` | `All checks passed!` |
| `.venv\Scripts\ruff format --check src tests` | `30 files already formatted` |
| `uv build --wheel --out-dir <scratchpad>\dist` + list zip entries matching `migrations` | `['jobbot/migrations/0001_init.sql', 'jobbot/migrations/__init__.py']` |
| Mutation check (scratchpad script): ran `test_failing_migration_rolls_back_ddl_and_version` against a naive runner (`executescript` in legacy mode, then `rollback()`) | Test **failed** against the naive runner, as it should, so the test really detects non-atomic migrations |

## Acceptance criteria

| AC | Result | Evidence |
|---|---|---|
| AC-1 Schema only in migration files | PASS | `test_db_module_has_no_inline_ddl` (no `CREATE TABLE`/`CREATE INDEX` in `db.py` source) |
| AC-2 `0001_init.sql` == old schema | PASS | `test_init_migration_matches_legacy_schema` compares all `sqlite_master` rows (type, name, tbl_name, sql) with a DB built from the old `_SCHEMA` text |
| AC-3 Fresh DB: schema + latest version | PASS | `test_fresh_db_gets_schema_and_latest_version`, `test_schema_version_is_latest_migration` |
| AC-4 Reopen is idempotent | PASS | `test_reopen_is_idempotent`, `test_migrate_applies_pending_in_order` (second `migrate()` does not re-run an `INSERT`) |
| AC-5 Existing v1 DB keeps rows, not re-migrated | PASS | `test_existing_v1_db_keeps_rows_and_is_not_remigrated` (migration 1 replaced by invalid SQL; it would raise if re-run), `test_existing_v1_db_opens_with_real_migrations` (schema byte-identical before/after, rows intact) |
| AC-6 Pre-versioning DB (v0 + table) opens | PASS | `test_pre_versioning_db_opens` (rows intact, ends at `SCHEMA_VERSION`) |
| AC-7 Newer DB raises, untouched | PASS | `test_newer_db_version_raises` (`MigrationError` "newer", version unchanged, file deletable so the connection was closed) |
| AC-8 Failed migration rolls back DDL + version | PASS | `test_failing_migration_rolls_back_ddl_and_version` (0001 stays applied; 0002's `CREATE TABLE b` and version bump are gone, checked from a fresh connection), `test_connection_mode_restored_after_failure`, `test_failed_migration_in_jobstore_closes_connection`; mutation check above |
| AC-9 Bad numbering raises | PASS | `test_gap_in_numbers_raises`, `test_not_starting_at_one_raises`, `test_duplicate_numbers_raise`, `test_no_migrations_raises`, `test_migrate_validates_injected_list`; `test_loader_reads_folder_sorted_and_ignores_other_files` covers discovery and sorting |
| AC-10 `.sql` ships in the wheel | PASS | wheel listing above; no `pyproject.toml` change needed |
| AC-11 Suite + ruff clean | PASS | `85 passed`; ruff check and format clean |

## Design summary

- Discovery: `importlib.resources.files("jobbot.migrations")`, files matching `^(\d{4})_\w+\.sql$`,
  sorted by number; anything else in the folder is ignored. `load_migrations(source)` takes an
  optional directory, which the tests use for fake migration sets.
- Atomicity: Python 3.13's legacy transaction mode makes `executescript()` COMMIT first, so the
  runner temporarily sets `conn.autocommit = True` and issues `BEGIN IMMEDIATE` / `COMMIT` /
  `ROLLBACK` itself; the script and `PRAGMA user_version = N` run inside that one transaction.
  The previous `autocommit` mode is restored in `finally` (`db.py:91-116`).
- Concurrency: `BEGIN IMMEDIATE` takes the write lock and the version is re-read under it, so a
  second process that opens an old DB at the same time skips migrations already applied
  (`db.py:98-104`).
- `SCHEMA_VERSION = load_migrations()[-1].version` (`db.py:120`), so it cannot drift from the files.

## Findings (by severity)

No high or medium findings.

1. **Low:** Migration files are not checked for `BEGIN`/`COMMIT`/`ROLLBACK`/`VACUUM`/`PRAGMA foreign_keys`
   (`db.py:105`). Such a statement would break the per-migration atomicity. A text check was not
   added because `CREATE TRIGGER ... BEGIN ... END` would give false positives. Mitigation: the rule
   is in `src/jobbot/migrations/__init__.py`; reviewers of new migrations must check it.
2. **Low:** If another process holds the write lock for longer than sqlite3's default 5 s timeout,
   `BEGIN IMMEDIATE` (`db.py:98`) raises a raw `sqlite3.OperationalError` ("database is locked")
   instead of `MigrationError`. Nothing is half-applied in that case; only the error type differs.
3. **Low:** `SCHEMA_VERSION` is computed at import time (`db.py:120`), so a broken migrations folder
   (gap, duplicate, missing) makes `import jobbot.db` fail, and with it any CLI command that imports
   it. This is intentional ("fail loudly"), but it affects commands that do not touch the DB.
4. **Info:** The concurrent-migration branch (version re-read under the lock and skip,
   `db.py:101-104`) and the `KeyboardInterrupt` rollback path (`db.py:109-114`) have no automated
   test; both are simple, but they are only verified by reading the code.
5. **Info:** No backup of `jobs.db` is taken before migrating. This doesn't matter for 0001 (a no-op
   on existing DBs), but a future destructive migration needs human approval (workflow section 9)
   and should consider a copy first.

## Deferred / for other owners

- CLAUDE.md (Layout, Step 2 notes) and ADR-0003 should mention `src/jobbot/migrations/` and the
  "add a new `NNNN_*.sql`, never edit a released one" rule. Other agents are handling those docs;
  they were not edited here.
- A `jobbot db status` style command to show the schema version: out of scope.
