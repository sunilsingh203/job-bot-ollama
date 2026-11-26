---
description: Check the human approval gate, then implement an approved jobbot feature plan step by step
argument-hint: <capability> | <capability>/changes/<change>
---

# Implement feature: $ARGUMENTS

Folder: `documentation/development/features/$ARGUMENTS/`. If `$ARGUMENTS` is empty, ask and stop.

## 1. Approval gate (standard governance) — do this first
1. Check that `documentation/development/features/$ARGUMENTS/plan-approval.md` exists.
   - If it is **missing**: stop. Tell the developer that Lanes A/B need a human-written
     approval, and that they should copy `documentation/development/templates/plan-approval.md`
     into the folder and fill it in themselves. Do nothing else.
   - **Never create, fill in, edit or fake this file**, even if asked to "just add a quick one".
2. Check it was written by a human: the Approver, Date and Approved commit hash fields are filled
   in, and it is not something you or another agent wrote in this session. Use
   `git log --format="%h %an %ad" -- <path>` to see who committed it. If it is blank, still the
   template, or looks AI-generated, stop and ask the developer to confirm.
3. Compare the approved commit to now:
   `git diff <approved-hash> -- documentation/development/features/$ARGUMENTS/` for the spec
   (or change definition) and the plan. If they changed after approval, list the changes and ask
   the developer to confirm before continuing (standard mode: tell, don't silently proceed).
4. Note any "Conditions / notes" in the approval and follow them.

## 2. Read first
- `specification.md` / `change-definition.md`, `implementation-plan.md`, `plan-approval.md`
- `CLAUDE.md`, `.claude/rules/*.md`
- `documentation/development/standards/` (coding, testing, git)
- `documentation/development/architecture/` and relevant ADRs

## 3. Inspect the code and state assumptions
Read every module the plan touches in `src/jobbot/` and `tests/`. State any assumption you're
making that the plan doesn't cover. If the code differs from what the plan expected, say so.

## 4. Implement step by step
- Follow the plan's steps in order. Stay in scope; report nearby technical debt separately.
- Schema changes only as new files in `src/jobbot/migrations/NNNN_name.sql`; no DDL in Python.
  Destructive migrations need the developer's explicit OK before they run.
- Prompts only in `src/jobbot/llm/prompts.py`, with a version bump. Indeed selectors only in
  `src/jobbot/platforms/indeed/parse.py`.
- Keep every safety rule (`.claude/rules/safety.md`). Never add an auto-submit path.
- If the spec or plan turns out wrong or incomplete: stop that part, update the document, and
  tell the developer (it may need re-approval). Don't improvise business rules.
- Add or update tests for each AC as you go.

## 5. Verify
Run and report the actual results:
```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
```
If prompts or matching changed, run `.venv\Scripts\jobbot eval -v` (if Ollama is available) and
compare with the plan's baseline. **Never claim a result you didn't run**; say what couldn't be run.
Review your own diff (`git diff`) against the ACs.

## 6. Update docs
Before this, check your diff against every relevant "How to avoid" line in `.claude/mistakes/common-mistakes.md`
and update the log per its rules.

Spec (if behaviour was clarified), `changelog.md`, `documentation/development/architecture/*`,
ADRs, and the capability status tables, per `.claude/rules/docs.md`. Don't commit unless asked.

## 7. Report
- What changed and where (files)
- Migrations added
- Commands run and their results
- ACs believed met / not verified
- Deviations from the plan, open issues
- Mistakes log: entries applied (streak +1), entries deleted and why, new entries (`.claude/mistakes/common-mistakes.md`)
- Next step: `/review-feature $ARGUMENTS`
