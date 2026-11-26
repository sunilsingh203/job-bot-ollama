# Change definition: SQL migration files for the job store

- **Capability:** job-store (`src/jobbot/db.py`, SQLite `data/jobs.db`)
- **Lane:** B (material change)
- **Governance:** standard
- **Date:** 2026-11-26
- **Related decision:** ADR-0003-sql-migration-files (`documentation/development/decisions/`)
- **Approval:** given by the developer in chat on 2026-11-26. The approver may add `plan-approval.md`.

## What

Move the job-store schema out of the Python string `_SCHEMA` in `db.py` into versioned SQL
migration files under `src/jobbot/migrations/` (`NNNN_<name>.sql`), and replace the
"run the CREATE script and set `user_version = 1`" code with a small migration runner that
applies pending migrations in order, tracked with SQLite's `PRAGMA user_version`.

## Why

The workflow rules (section 9, Database Authority) say every schema change must be an
explicit SQL migration file and application code must never be the only record of the
schema. Today the schema exists only as a Python string, and there is no way to evolve it
(add a column for the review dashboard, the form filler, etc.) without hand-written,
untracked `ALTER` code. Migrations also make the schema reviewable as plain SQL.

## Current behaviour

- `JobStore.__init__` runs `executescript(_SCHEMA)` (`CREATE TABLE IF NOT EXISTS jobs ...`
  plus `idx_jobs_status` and `idx_jobs_desc`) on every open, then unconditionally sets
  `PRAGMA user_version = 1` (`SCHEMA_VERSION`).
- A DB with a higher `user_version` would be silently downgraded to 1.
- There is no mechanism for schema changes after version 1.

## New behaviour

- The schema lives in `src/jobbot/migrations/0001_init.sql`, which reproduces the current
  table and both indexes exactly (keeping `IF NOT EXISTS`).
- On open, `JobStore` runs the migration runner:
  1. Discover `NNNN_*.sql` files in the `jobbot.migrations` package
     (`importlib.resources`), sort by number, and require the numbers to be contiguous
     from 1 with no duplicates. Otherwise fail loudly (`MigrationError`).
  2. Read `PRAGMA user_version`. If it is greater than the newest known migration, raise
     `MigrationError` ("database was created by a newer jobbot") and do not touch the DB.
  3. Apply each migration with a number greater than the current version, in order. Each
     migration and its `PRAGMA user_version = N` bump run in one transaction: either both
     happen or neither does.
- `SCHEMA_VERSION` equals the newest migration number (derived from the files).
- The `JobStore` public API is unchanged.

## Scope

- `src/jobbot/db.py` (remove `_SCHEMA`, add the runner, call it from `JobStore`)
- `src/jobbot/migrations/__init__.py`, `src/jobbot/migrations/0001_init.sql`
- `tests/test_migrations.py`
- `pyproject.toml` only if the `.sql` files would not ship in the wheel

## Out of scope

- Any change to the schema itself (no new tables, columns or indexes).
- Down-migrations / rollback to older versions.
- A CLI command for migration status (can come later).
- Updating CLAUDE.md and other docs (handled separately).

## Compatibility

- Existing `data/jobs.db` files are at `user_version = 1` (created by the current code).
  They must open untouched: no migration runs, no data is lost or rewritten.
- DBs created before `user_version` existed (version 0 with the `jobs` table already
  present) still open: `0001_init.sql` uses `IF NOT EXISTS`, so it is a no-op apart from
  bumping the version to 1.
- A DB from a newer jobbot (version > latest known) is refused with a clear error instead
  of being silently downgraded.

## Acceptance criteria

- **AC-1** The schema is defined only in SQL migration files under `src/jobbot/migrations/`;
  `db.py` contains no `CREATE TABLE`/`CREATE INDEX` text.
- **AC-2** `0001_init.sql` produces exactly the same schema (`sqlite_master` entries) as the
  previous `_SCHEMA` string.
- **AC-3** A fresh DB gets the full schema and `user_version == SCHEMA_VERSION` (the latest
  migration number).
- **AC-4** Re-opening an up-to-date DB is idempotent: nothing is re-applied, data and
  version are unchanged.
- **AC-5** An existing version-1 DB with rows opens with all rows intact and is not
  re-migrated.
- **AC-6** A pre-versioning DB (table exists, `user_version = 0`) opens with its rows intact
  and ends at the latest version.
- **AC-7** A DB whose `user_version` is greater than the latest migration raises a clear
  `MigrationError` and its version is not changed.
- **AC-8** If a migration fails, both its DDL and its version bump are rolled back; earlier
  migrations in the same run stay applied.
- **AC-9** Migration numbering that is not contiguous from 1, has duplicates, or is empty
  raises `MigrationError`.
- **AC-10** The `.sql` files are included in the built wheel.
- **AC-11** The existing test suite still passes; ruff check and format are clean.

## Risks

- **Transactions and `executescript`:** in Python's legacy transaction mode,
  `executescript` commits any open transaction first, which would break atomicity. The
  runner must use a transaction mode where it controls `BEGIN`/`COMMIT` itself (verified by
  a test, AC-8).
- **Migration files with their own `BEGIN`/`COMMIT`** or statements that cannot run in a
  transaction (`VACUUM`, `PRAGMA foreign_keys`) would break atomicity. Mitigation: a rule
  documented in the migrations package; review new migrations.
- **Two processes opening an old DB at once** (e.g. dashboard + CLI) could both try to
  migrate. Mitigation: take the write lock (`BEGIN IMMEDIATE`) and re-read the version inside
  the transaction before applying.
- **Packaging:** if the `.sql` files were not shipped, an installed jobbot could not create a
  DB. Mitigation: AC-10.
