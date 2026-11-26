# Database rules

Details: `documentation/development/architecture/data.md`, ADR-0003.

- SQLite at `data/jobs.db`, accessed only through `JobStore` (`src/jobbot/db.py`).
- **Every schema change is a migration file** `src/jobbot/migrations/NNNN_name.sql` (4-digit number, snake_case name). `JobStore` applies files numbered above `PRAGMA user_version`, in order, then sets `user_version`.
- **No silent DDL:** no `CREATE TABLE` / `ALTER TABLE` / `DROP` in Python code.
- Never edit a migration that has been applied; add a new one.
- **Destructive or hard-to-reverse changes** (drop table/column, create-copy-rename, status rewrites, bulk deletes) need the developer's explicit approval before they run. Suggest backing up `data/jobs.db` first.
- List every migration explicitly in the implementation plan.
- Use `?` parameters for every value. Never format scraped, user or LLM text into SQL.
- Status changes go through `JobStore` methods. Keep the status lifecycle in `db.py`, `architecture/data.md` and the specs in sync.
- Tests use `tmp_path` databases; cover a fresh DB and an upgrade from an older `user_version`. Never touch the real `data/jobs.db` in tests.
- N/A: least-privilege DB user (SQLite has no users).
