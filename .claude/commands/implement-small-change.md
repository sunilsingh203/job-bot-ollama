---
description: Implement a planned Lane C small change after the developer's go-ahead
argument-hint: <change>
---

# Implement small change: $ARGUMENTS

Folder: `documentation/development/changes/$ARGUMENTS/`. If `$ARGUMENTS` is empty, ask and stop.

## 0. Branch check
Run `git branch --show-current`. You must be on this work's branch (`fix/$ARGUMENTS`), the one created
at `/plan-small-change` from `develop`. If you are on `develop` or `main`, or on another work's branch,
stop and tell the developer. Don't commit feature work to `develop` or `main`. If `develop` has
moved ahead (`git log --oneline HEAD..origin/develop` after `git fetch`), say so and offer to
merge it in first.

## 1. Go-ahead check
- `request.md` and `implementation-plan.md` must exist. If the plan is missing, suggest
  `/plan-small-change $ARGUMENTS` and stop.
- Lane C needs the developer's go-ahead: a line like `Approved to implement: <date>` in
  `request.md`, or an explicit go-ahead in this chat. If neither is there, ask for it and stop.
  (No `plan-approval.md` is needed for Lane C. Never create one.)

## 2. Read first
- `request.md`, `implementation-plan.md`
- `CLAUDE.md`, `.claude/rules/*.md`, `documentation/development/standards/coding.md` and `testing.md`

## 3. Inspect the code and state assumptions
Read the files the plan names in `src/jobbot/` and `tests/`. State any assumption not in the plan.

## 4. Implement
- Follow the plan; stay in scope.
- If it turns out bigger than planned (touches the schema, a prompt, a safety rule, the approval
  flow, or the Indeed/Ollama integration), stop and recommend Lane B.
- Keep all safety rules. Add or update tests, including a regression test for a bug fix.

## 5. Verify
```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
```
Plus `.venv\Scripts\jobbot eval -v` if matching changed. Record exact results. **Never claim a
result you didn't run.**

## 6. Update docs
Before this, check your diff against every relevant "How to avoid" line in `.claude/mistakes/common-mistakes.md`
and update the log per its rules.

If documented behaviour changed: the capability's `specification.md` and a line in its
`changelog.md`; architecture docs if data or modules changed. Don't commit unless asked.

## 7. Report
- Files changed
- Commands run and results
- Docs updated
- Mistakes log: entries applied (streak +1), entries deleted and why, new entries (`.claude/mistakes/common-mistakes.md`)
- Next step: `/review-small-change $ARGUMENTS`
