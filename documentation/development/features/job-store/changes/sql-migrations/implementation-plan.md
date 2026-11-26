# Implementation plan: SQL migration files for the job store

See `change-definition.md` for the what/why and acceptance criteria (AC-1..AC-11).
Approval: given by the developer in chat on 2026-11-26.

## Affected layers

| Layer | Impact |
|---|---|
| DB | Schema moves from a Python string to `src/jobbot/migrations/0001_init.sql`. New runner tracks versions with `PRAGMA user_version`. **No schema change.** |
| API (Python) | `JobStore` public API unchanged. New module-level `MigrationError`, `Migration`, `load_migrations()`, `migrate()` in `db.py`. `SCHEMA_VERSION` is now derived from the migration files. |
| Frontend | None (dashboard not built yet). |
| Security / permissions | None. Local SQLite file; no new inputs. Migration SQL comes only from the installed package. |
| Packaging | `.sql` files must ship in the wheel. Build backend is hatchling with `packages = ["src/jobbot"]`, which includes all non-ignored files in the package directory; verify by building a wheel. No `pyproject.toml` change expected. |
| Tests | New `tests/test_migrations.py`. |
| Docs | This change folder only (CLAUDE.md and ADR handled by others). |

## Database changes

- **Schema changes: none.**
- New file `src/jobbot/migrations/0001_init.sql`: the existing `jobs` table, `idx_jobs_status`
  and `idx_jobs_desc`, copied verbatim from `_SCHEMA`, including `IF NOT EXISTS`.
- Version tracking: `PRAGMA user_version` (already set to 1 by the current code, so existing
  DBs are already "at migration 1").

## Runner design (`src/jobbot/db.py`)

```python
class MigrationError(RuntimeError): ...

@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

def load_migrations(source: Traversable | None = None) -> list[Migration]
def migrate(conn: sqlite3.Connection, migrations: Sequence[Migration] | None = None) -> int
SCHEMA_VERSION: int = load_migrations()[-1].version
```

- **Discovery:** `importlib.resources.files("jobbot.migrations")` (or an injected directory for
  tests). Files matching `^(\d{4})_\w+\.sql$` are loaded (UTF-8) and sorted by number; other
  files are ignored.
- **Validation:** numbers must be exactly `1..N` (no gaps, no duplicates, not empty), else
  `MigrationError` naming the offending files. `migrate()` re-validates an injected list.
- **Version check:** read `PRAGMA user_version`. If it is above the newest migration, raise
  `MigrationError` without writing anything.
- **Atomic apply:** in Python 3.13's default (legacy) transaction mode, `executescript()`
  issues a `COMMIT` before running, so an outer transaction cannot wrap it. The runner
  therefore switches the connection to `autocommit = True` (PEP 249 mode, Python >= 3.12;
  no implicit BEGIN/COMMIT by the sqlite3 module) for the duration of the migration, and for
  each pending migration:
  1. `BEGIN IMMEDIATE` (takes the write lock, so a second process waits instead of racing),
  2. re-read `user_version` inside the transaction; skip if another process already applied it,
  3. `executescript(migration.sql)`, then `PRAGMA user_version = N`,
  4. `COMMIT`; on any exception `ROLLBACK` and raise `MigrationError` (chained) naming the file.
  SQLite DDL and `user_version` are transactional, so the rollback removes both.
  The previous `autocommit` setting is restored in a `finally` block, so the rest of
  `JobStore` keeps its current transaction behaviour.
- **JobStore:** `__init__` calls `migrate(self.conn)` instead of `executescript(_SCHEMA)`; if
  migration fails the connection is closed before the error propagates.
- **Rules for migration authors** (in `migrations/__init__.py` docstring): never edit a
  released migration; add a new `NNNN_name.sql`; no `BEGIN`/`COMMIT`/`VACUUM`/`PRAGMA foreign_keys`
  inside a migration (the runner owns the transaction).

## Test plan (`tests/test_migrations.py`, all use `tmp_path`, no LLM, no network)

| AC | Test |
|---|---|
| AC-1 | `test_db_module_has_no_inline_ddl` (source of `db.py` has no `CREATE TABLE/INDEX`) |
| AC-2 | `test_init_migration_matches_legacy_schema` (compare `sqlite_master` with a DB built from the old `_SCHEMA` text) |
| AC-3 | `test_fresh_db_gets_schema_and_latest_version`, `test_schema_version_is_latest_migration` |
| AC-4 | `test_reopen_is_idempotent` |
| AC-5 | `test_existing_v1_db_keeps_rows_and_is_not_remigrated` (a v1 DB whose rows would be wiped if 0001 re-ran is detected via a sentinel) |
| AC-6 | `test_pre_versioning_db_opens` |
| AC-7 | `test_newer_db_version_raises` |
| AC-8 | `test_failing_migration_rolls_back_ddl_and_version`, `test_connection_mode_restored_after_failure` |
| AC-9 | `test_gap_in_numbers_raises`, `test_duplicate_numbers_raise`, `test_no_migrations_raises`, `test_loader_ignores_non_migration_files` |
| AC-10 | Build a wheel with `uv build --wheel` into the scratchpad and list its contents (manual check, recorded in review.md) |
| AC-11 | Full `pytest -q`, `ruff check src tests`, `ruff format --check src tests` |

## Steps

1. Write `change-definition.md` and this plan.
2. Add `src/jobbot/migrations/__init__.py` and `0001_init.sql`.
3. Replace `_SCHEMA` in `db.py` with the runner; wire it into `JobStore.__init__`.
4. Add `tests/test_migrations.py`.
5. Run pytest and ruff; build a wheel to check packaging.
6. Write `review.md`.

## Risks / open questions

- See `change-definition.md`, Risks. No open questions; ADR-0003 records the location decision.
