---
description: Draft the implementation plan for a jobbot capability (Lane A) or material change (Lane B)
argument-hint: <capability> | <capability>/changes/<change>
---

# Plan feature: $ARGUMENTS

Write `documentation/development/features/$ARGUMENTS/implementation-plan.md` from
`documentation/development/templates/implementation-plan.md`.

If `$ARGUMENTS` is empty, ask which capability and stop.

## 1. Read first
- `documentation/development/features/$ARGUMENTS/specification.md` (Lane A) or
  `change-definition.md` (Lane B, plus the capability's `specification.md`). If neither exists,
  stop and suggest `/define-feature $ARGUMENTS`.
- `CLAUDE.md`, `.claude/rules/*.md`, `.claude/mistakes/common-mistakes.md` (plan so the known mistakes can't recur)
- `documentation/development/AI-DEVELOPMENT-WORKFLOW.md` (sections 2, 8, 9, 10, 12)
- `documentation/development/architecture/` (overview, security, data)
- `documentation/development/standards/coding.md` and `testing.md`
- Relevant ADRs in `documentation/development/decisions/`

## 2. Inspect the code
Read the modules the plan will touch in `src/jobbot/` and their tests in `tests/`. Check the
latest migration number in `src/jobbot/migrations/` and the current statuses in `db.py`. Base the
plan on the real code.

## 3. State assumptions
List what you understood, assumptions, and any spec gaps or conflicts. If the spec has open
questions that block the plan, ask and stop.

## 4. Write the plan
Cover every template section:
- Affected layers: DB / core logic / CLI / dashboard / config / prompts / safety / tests / docs
- **Database changes listed explicitly**: tables, columns, indexes, constraints, and the
  migration file names (`src/jobbot/migrations/NNNN_name.sql`). Mark destructive ones as
  needing approval.
- Module interfaces (signatures, return values, exceptions) and CLI commands (name, flags, output)
- Dashboard screens and the functions/status transitions they use (if any)
- Prompt changes and the version bump (if any), plus a `jobbot eval` before/after step
- Test plan mapped to every AC (test file::name, or the manual check); mark tests needing `-m llm`
- Ordered implementation steps
- Risks, open questions, ADRs needed
- How each safety rule in `.claude/rules/safety.md` is kept

Record the base commit (`git rev-parse --short HEAD`). Don't touch source code. **Never create
`plan-approval.md`.**

## 5. Report
- File written (path)
- DB impact, safety impact, ADRs needed, open questions
- Next step: the developer reviews the spec and plan, commits them, and writes
  `documentation/development/features/$ARGUMENTS/plan-approval.md` by hand (template:
  `documentation/development/templates/plan-approval.md`). Then `/implement-feature $ARGUMENTS`.
