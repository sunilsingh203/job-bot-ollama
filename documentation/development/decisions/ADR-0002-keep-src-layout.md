# ADR-0002: Keep the `src/jobbot` layout instead of `apps/`

**Status:** Accepted, 2026-11-26

## Context
The workflow blueprint suggests `apps/web`, `apps/api` and `apps/db`. jobbot is already built as
one installable Python package in `src/jobbot` (hatchling, `jobbot` console script), with steps 1
and 2 working and tests in `tests/`. It has no separate frontend or backend service: the CLI and
the planned Streamlit dashboard call the same package in-process.

## Options
1. **Restructure into `apps/`** (`apps/cli`, `apps/dashboard`, `apps/core`, `apps/db`): matches
   the blueprint, but splits one package into several, breaks imports, packaging and the
   documented commands, and adds nothing for a single-process tool.
2. **Keep `src/jobbot`** and map the blueprint's folders onto it.

## Decision
Keep the **`src/` layout with one package**. Mapping:

| Blueprint | jobbot |
|---|---|
| `apps/web` | `cli.py`, `dashboard/` (planned) |
| `apps/api` | `matcher/`, `llm/`, `resumes/`, `platforms/`, `pipeline.py`, `db.py` |
| `apps/db` | `src/jobbot/migrations/` ([ADR-0003](ADR-0003-sql-migration-files.md)) |

Docs go in `documentation/`, agent rules in `CLAUDE.md` and `.claude/`.

## Consequences
- No churn in working code; `pip install -e .` and `jobbot` keep working.
- Layer boundaries are kept by module rules, not folders: platform code stays in
  `platforms/<name>/` and must not leak into `matcher/` or `llm/`; prompts only in `llm/prompts.py`.
- The dashboard will live inside the package and import it directly, with no API in between.
- If jobbot ever grows a separate service, revisit this ADR.
