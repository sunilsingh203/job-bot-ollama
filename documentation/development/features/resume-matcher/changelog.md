# Changelog: `resume-matcher`

## 2026-11-26: Documented as-built (retroactive spec + plan)

- Added `specification.md` (Purpose, Business rules BR-1..BR-12, data entities, AC-1..AC-35, OQ-1..OQ-17) and `implementation-plan.md`, both reconstructed from the code at commit `c3677ba`.
- No code changes. `pytest` run: 66 passed (whole suite). `jobbot eval` was not run.
- Status: awaiting review by the approver. `plan-approval.md` comes from the developer (by hand or recorded from chat, ADR-0005).

## 2026-11-21: Initial implementation (commit c3677ba)

- Step 1 matcher: settings/profile loading, Ollama JSON client with retry once, versioned prompts (`resume_profile_v1`, `decide_v1`), resume library + parser + cached LLM profiles, rule filters, startup/MNC resolution, LLM decision with post-checks and role × company-type resume selection, `decisions.jsonl` log.
- CLI: `jobbot resumes index/show`, `jobbot match`, `jobbot eval`, `--model`.
- Tests: `test_filters.py`, `test_company_type.py`, `test_select_resume.py`; 10 JD fixtures for `jobbot eval`.
