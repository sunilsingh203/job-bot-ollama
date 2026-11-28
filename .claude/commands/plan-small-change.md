---
description: Read a Lane C request.md and write a short implementation plan for a small jobbot change
argument-hint: <change>
---

# Plan small change: $ARGUMENTS

Folder: `documentation/development/changes/$ARGUMENTS/`. If `$ARGUMENTS` is empty, ask and stop.

## 0. Branch (do this before writing any file)
New work goes on its own branch, cut from the **latest `develop`** (ADR-0006,
`documentation/development/standards/git.md`). Branch name: `fix/$ARGUMENTS`.
- If you are already on that branch, continue.
- If it exists, `git switch` to it.
- Otherwise run `git status` (it must be clean; if not, stop and ask the developer),
  `git fetch origin`, `git switch develop`, `git pull --ff-only origin develop`, then
  `git switch -c <branch>`.
- Never write this work on `develop` or `main`. Report the branch name at the end.

## 1. Read first
- `documentation/development/changes/$ARGUMENTS/request.md`. If it doesn't exist, stop and ask
  the developer to write it (template: `documentation/development/templates/request.md`; see
  `documentation/development/changes/README.md`).
- `CLAUDE.md`, `.claude/rules/*.md`, `.claude/mistakes/common-mistakes.md` (plan so the known mistakes can't recur)
- `documentation/development/AI-DEVELOPMENT-WORKFLOW.md` (section 3, escalation rule)
- The spec of the related capability in `documentation/development/features/`, if any

## 2. Inspect the code
Read the modules and tests in `src/jobbot/` and `tests/` that the request touches. Find the
actual cause for a bug before planning a fix.

## 3. Check the lane
If the change affects business behaviour, DB schema or status meanings, a prompt or the decision
schema, a safety rule, the approval flow, shared code behaviour (`models.py`, `db.py`,
`config.py`, `llm/client.py`), or the Indeed/Ollama integration: **say so and recommend Lane B**,
with the reason. The developer decides. Stop until they do.

## 4. State assumptions and write the plan
Write `documentation/development/changes/$ARGUMENTS/implementation-plan.md` from
`documentation/development/templates/implementation-plan.md`. Keep it short: what you
understood, files to change, DB impact (normally none), safety impact, tests to add or update,
steps, open questions. Don't change code yet.

## 5. Report
- Plan written (path); lane confirmed or escalation recommended
- Open questions
- Next step: the developer gives the go-ahead in chat (or adds `Approved to implement: <date>` to
  `request.md`), then `/implement-small-change $ARGUMENTS`
