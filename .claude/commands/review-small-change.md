---
description: Verify a Lane C small change against its request and write a brief review.md
argument-hint: <change>
---

# Review small change: $ARGUMENTS

Folder: `documentation/development/changes/$ARGUMENTS/`. If `$ARGUMENTS` is empty, ask and stop.

## 0. Branch check
Work on this feature's or change's own branch (cut from `develop`; see
`documentation/development/standards/git.md`). If you are on `develop` or `main`, stop and ask.

## 1. Read first
- `request.md` (especially "Done when"), `implementation-plan.md`
- `CLAUDE.md`, `.claude/rules/*.md`
- `documentation/development/templates/review.md`

## 2. Inspect
Look at the diff (`git status`, `git diff`, or the branch's commits) and read the changed files in
`src/jobbot/` and `tests/`. State which diff you reviewed.

## 3. Check
- Does it do what `request.md` asks, and match the plan?
- Safety rules still hold; untrusted input handled; no personal data or secrets in the diff.
- No schema, prompt or safety-rule change slipped in (if one did, flag it as Lane B).
- Tests cover the change (regression test for a bug fix); docs and changelog updated if needed.
- No unrelated changes.

## 4. Run
```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
```
Plus the "Done when" check from `request.md` if it can be run safely without opening Indeed or
needing the developer (otherwise list it for the developer to run). **Never claim a result you
didn't run.**

## 5. Write review.md
Write a brief `documentation/development/changes/$ARGUMENTS/review.md` from the template: verdict,
request vs. result, findings ranked by severity with file:line, commands run and results. Don't
fix code in this command.

For every finding that is a defect Claude introduced and could happen again, add an entry to
`.claude/mistakes/common-mistakes.md` (or bump an existing one's `Seen` and reset its streak). Also check the
implementation against the log's existing "How to avoid" lines.

## 6. Report
- Verdict and findings count
- Mistakes log: new or bumped entries
- Commands run and results
- Next step: fix findings (`/implement-small-change $ARGUMENTS` again), or done
