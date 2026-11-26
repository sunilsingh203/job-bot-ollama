# Review: <capability or change>

> Lane A/B: `features/<capability>/[changes/<change>/]review.md`. Lane C: `changes/<change>/review.md` (brief).

| | |
|---|---|
| Reviewer | AI agent / the developer |
| Date | YYYY-MM-DD |
| Reviewed commit / diff | `<hash>` or "working tree on <branch>" |
| Spec / request | link |

## 1. Summary
Verdict in one or two lines: ready / ready with fixes / not ready.

## 2. Acceptance criteria
| AC | Result | Evidence (test, command output, file:line) |
|---|---|---|
| AC-1 | pass / fail / partial / not verified | |

## 3. Findings
Ranked by severity. Severity: **critical** (breaks a safety rule, loses or leaks data),
**high** (wrong behaviour, AC not met), **medium** (edge case, missing test), **low** (style, docs).

| # | Severity | File:line | Finding | Suggested fix |
|---|---|---|---|---|
| F-1 | | | | |

## 4. Checklist
- [ ] Safety rules hold: no auto-submit, local-only, headed browser, no scripted login/CAPTCHA bypass, no invented form facts
- [ ] Untrusted input handled: scraped HTML, JD text, LLM output (schema + pydantic), SQL parameters
- [ ] Schema changes are migration files in `src/jobbot/migrations/`
- [ ] Prompts changed only in `llm/prompts.py`, with a version bump
- [ ] Indeed selectors only in `platforms/indeed/parse.py`
- [ ] No personal data or secrets in the diff
- [ ] Tests added/updated and **run** (paste the command and result)
- [ ] `jobbot eval` run if matching or prompts changed
- [ ] Docs updated (spec, architecture, changelog)
- [ ] No unrelated changes

## 5. Commands run
```
.venv\Scripts\python -m pytest      -> <result>
.venv\Scripts\ruff check src tests  -> <result>
```

## 6. Remediation
Filled in by `/remediate-review`.

| # | Resolution | Notes |
|---|---|---|
| F-1 | resolved / deferred / rejected | why, and where it was fixed |
