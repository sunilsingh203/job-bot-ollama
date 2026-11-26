# ADR-0003: Explicit SQL migration files applied by `PRAGMA user_version`

**Status:** Accepted, 2026-11-26

## Context
Step 2 created the `jobs` table with a `CREATE TABLE IF NOT EXISTS` script inside `db.py` and set
`PRAGMA user_version = 1`. That works for one version, but `IF NOT EXISTS` can't add columns to an
existing database, and the code becomes the only record of the schema. The review dashboard and
form filler will need new columns and statuses on the developer's existing `data/jobs.db`. The
workflow requires every schema change to be an explicit SQL migration file.

## Options
1. **Keep DDL in Python** and add `ALTER TABLE` branches per version: the schema history is
   scattered through code and hard to review.
2. **A migration library** (Alembic, yoyo): powerful, but a new dependency and more machinery than
   one local SQLite file needs; Alembic expects SQLAlchemy.
3. **Plain SQL files in the package, applied by `JobStore` using `PRAGMA user_version`.**

## Decision
Option 3.
- Migrations live in **`src/jobbot/migrations/NNNN_name.sql`** (e.g. `0001_init.sql`), a
  4-digit number and a short snake_case name. They ship inside the package, so an installed
  `jobbot` can always upgrade its own database.
- On open, `JobStore` reads `PRAGMA user_version`, applies every file with a higher number in
  order, and sets `user_version` to the number of the last file applied.
- No `CREATE TABLE` / `ALTER TABLE` in Python code.
- An applied migration is never edited; corrections go in a new file.
- Destructive migrations (drops, status rewrites, data deletes) need the developer's explicit
  approval before they run.

## Consequences
- The schema history is readable SQL, reviewable in a diff, and listed in implementation plans.
- Each migration should run in a transaction so a failure leaves `user_version` unchanged.
- SQLite's limited `ALTER TABLE` means some changes need the create-copy-rename pattern; those
  count as hard-to-reverse and need approval.
- Tests must cover a fresh database and an upgrade from an older `user_version`.
- There are no down-migrations. Rollback is a backup of `data/jobs.db`.
