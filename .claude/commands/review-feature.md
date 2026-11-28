---
description: Review a jobbot feature implementation against its spec and every acceptance criterion; write review.md
argument-hint: <capability> | <capability>/changes/<change>
---

# Review feature: $ARGUMENTS

Write `documentation/development/features/$ARGUMENTS/review.md` from
`documentation/development/templates/review.md`. If `$ARGUMENTS` is empty, ask and stop.

## 0. Branch check
Work on this feature's or change's own branch (cut from `develop`; see
`documentation/development/standards/git.md`). If you are on `develop` or `main`, stop and ask.

## 1. Read first
- `specification.md` (or `change-definition.md` + the capability spec), `implementation-plan.md`,
  `plan-approval.md` (read only; note its approved commit and conditions)
- `CLAUDE.md`, `.claude/rules/*.md`
- `documentation/development/architecture/` (overview, security, data), relevant ADRs
- `documentation/development/standards/` (coding, testing)

## 2. Inspect the implementation
- Find the changes: `git log` / `git diff <approved-hash>..HEAD` and the working tree
  (`git status`, `git diff`).
- Read every changed file in `src/jobbot/`, `src/jobbot/migrations/` and `tests/`.
- State your assumptions (e.g. which commit range you reviewed).

## 3. Check
- **Every AC**: pass / fail / partial / not verified, with evidence (test name, command output,
  file:line). Don't mark an AC "pass" without evidence.
- Safety rules: no auto-submit, local-only, headed browser, no scripted login or CAPTCHA bypass,
  daily caps, no invented form facts (LLM answers flagged).
- Untrusted input: scraped HTML, JD text, LLM output validated (schema + pydantic, retry once
  then fail), SQL parameters.
- DB: schema changes only as migration files; `user_version` handling; destructive changes approved.
- Boundaries: prompts only in `llm/prompts.py` with a version bump; selectors only in
  `platforms/indeed/parse.py`; no platform code in `matcher/` or `llm/`.
- Tests exist for each AC, the plan's test plan was followed, and docs match the code.
- No personal data or secrets in the diff; no unrelated changes.

## 4. Run
```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
```
Run `.venv\Scripts\jobbot eval -v` if matching or prompts changed and Ollama is available.
Record the exact commands and results. **Never claim a result you didn't run.**

## 5. Write review.md
Findings ranked by severity (critical → high → medium → low), each with file:line and a suggested
fix. Leave the Remediation table for `/remediate-review`. Don't fix code in this command.

For every finding that is a defect Claude introduced and could happen again, add an entry to
`.claude/mistakes/common-mistakes.md` (or bump an existing one's `Seen` and reset its streak). Also check the
implementation against the log's existing "How to avoid" lines.

## 6. Report
- Verdict (ready / ready with fixes / not ready)
- AC summary (n pass, n fail, n not verified)
- Count of findings by severity
- Mistakes log: new or bumped entries
- Next step: `/remediate-review $ARGUMENTS`, or done
