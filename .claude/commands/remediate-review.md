---
description: Fix the findings in a jobbot feature review.md and record how each was resolved
argument-hint: <capability> | <capability>/changes/<change>
---

# Remediate review: $ARGUMENTS

Folder: `documentation/development/features/$ARGUMENTS/`. If `$ARGUMENTS` is empty, ask and stop.

## 1. Read first
- `review.md` (the findings), `specification.md` / `change-definition.md`,
  `implementation-plan.md`, `plan-approval.md` (read only)
- `CLAUDE.md`, `.claude/rules/*.md`, `documentation/development/standards/`

If `review.md` doesn't exist, stop and suggest `/review-feature $ARGUMENTS`.

## 2. Inspect and state assumptions
Read the code each finding points to. For each finding, decide: fix it, defer it, or reject it.
State your reasoning. **Ask the developer** before:
- rejecting or deferring a critical or high finding
- any fix that changes the spec, the DB schema, a prompt, or a safety rule (it may need
  re-approval or escalation; see the workflow, sections 3 and 4)

## 3. Fix
- Work through findings from most to least severe. Stay in scope.
- Same rules as implementation: migrations only in `src/jobbot/migrations/`, prompts only in
  `llm/prompts.py` (version bump), selectors only in `platforms/indeed/parse.py`, all safety rules.
- Add a regression test for each fixed bug.

## 4. Verify
```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
```
Plus `.venv\Scripts\jobbot eval -v` if matching or prompts changed. **Never claim a result you
didn't run.**

## 5. Record
Fill the Remediation table in `review.md`: each finding as **resolved** (where, which test),
**deferred** (why, and where it's tracked) or **rejected** (why). Update the spec,
`changelog.md` and architecture docs if behaviour changed. Never touch `plan-approval.md`.
If a fix adds an automated guard (a test, a lint rule, a hook) for an entry in
`.claude/mistakes/common-mistakes.md`, delete that entry and name the guard in the report.

## 6. Report
- Findings resolved / deferred / rejected (counts and ids)
- Files changed; commands run and results
- Mistakes log: entries deleted (and the guard that replaced each)
- Anything that needs the developer's decision or re-approval
- Next step: re-run `/review-feature $ARGUMENTS` if fixes were substantial, otherwise done
