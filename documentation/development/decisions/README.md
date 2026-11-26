# Architecture Decision Records

An ADR records a significant choice: the context, the options, what we chose and the consequences.
Write one when a decision changes architecture, data, safety rules, dependencies or external
integrations (see the workflow, section 10).

File name: `ADR-NNNN-short-title.md`. Sections: Status, Context, Options, Decision, Consequences.
Status is one of: Proposed, Accepted, Superseded by ADR-NNNN, Deprecated. Don't rewrite an
accepted ADR; supersede it with a new one.

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-0001](ADR-0001-local-only-llm.md) | Local-only LLM via Ollama, no cloud APIs | Accepted | 2026-11-26 |
| [ADR-0002](ADR-0002-keep-src-layout.md) | Keep the `src/jobbot` layout instead of `apps/` | Accepted | 2026-11-26 |
| [ADR-0003](ADR-0003-sql-migration-files.md) | Explicit SQL migration files applied by `PRAGMA user_version` | Accepted | 2026-11-26 |
| [ADR-0004](ADR-0004-human-approval-never-auto-submit.md) | Human approval for every application; never auto-submit | Accepted | 2026-11-26 |
