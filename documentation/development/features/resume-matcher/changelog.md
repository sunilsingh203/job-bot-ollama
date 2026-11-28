# Changelog: `resume-matcher`

## 2026-11-27: LLM client timeouts are stop-the-run errors (job-store changes/llm-timeout-stops-run)

- `src/jobbot/llm/client.py`: new `LLMTimeout(LLMUnavailable)`. Any `httpx.TimeoutException` (connect, read, write, pool), on any attempt, now raises it instead of a plain `LLMError`, with no retry. The message names the model and `timeout_s` (formatted with `:g`, e.g. `600s`) and suggests a smaller model (`jobbot --model`) or a larger `llm.timeout_s`.
- `OllamaClient.__init__` takes an optional keyword-only `transport` (default `None` = httpx's normal transport); tests pass an `httpx.MockTransport`. Production callers don't pass it.
- Invalid JSON after the retry is still a plain `LLMError`. `resumes index`, `match` and `eval` still print `Error:` and exit 1 on a timeout, now with the hint.
- Spec: §7 note, §10 error table, AC-27..AC-29, OQ-3 (resolved). First client tests: `tests/test_llm_client.py`, with the shared fake client in `tests/conftest.py`.

## 2026-11-26: Documented as-built (retroactive spec + plan)

- Added `specification.md` (Purpose, Business rules BR-1..BR-12, data entities, AC-1..AC-35, OQ-1..OQ-17) and `implementation-plan.md`, both reconstructed from the code at commit `c3677ba`.
- No code changes. `pytest` run: 66 passed (whole suite). `jobbot eval` was not run.
- Status: awaiting review by the approver. `plan-approval.md` comes from the developer (by hand or recorded from chat, ADR-0005).

## 2026-11-21: Initial implementation (commit c3677ba)

- Step 1 matcher: settings/profile loading, Ollama JSON client with retry once, versioned prompts (`resume_profile_v1`, `decide_v1`), resume library + parser + cached LLM profiles, rule filters, startup/MNC resolution, LLM decision with post-checks and role × company-type resume selection, `decisions.jsonl` log.
- CLI: `jobbot resumes index/show`, `jobbot match`, `jobbot eval`, `--model`.
- Tests: `test_filters.py`, `test_company_type.py`, `test_select_resume.py`; 10 JD fixtures for `jobbot eval`.
