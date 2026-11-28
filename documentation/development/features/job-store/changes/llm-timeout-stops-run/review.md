# Review: job-store/changes/llm-timeout-stops-run

> Lane B: `features/job-store/changes/llm-timeout-stops-run/review.md`.

| | |
|---|---|
| Reviewer | AI agent |
| Date | 2026-11-28 |
| Reviewed commit / diff | `1d6f6fe` (`git diff d673962 1d6f6fe`); full suite re-run at `d3aafe1` on `docs/spec-driven-workflow` |
| Spec / request | [change-definition.md](change-definition.md), [implementation-plan.md](implementation-plan.md), [plan-approval.md](plan-approval.md) (approved at `dba1e52`, recorded from chat per ADR-0005) |

## 1. Summary
**Ready.** All 12 ACs pass, with evidence for each. The code change is small and does what the
plan says: `LLMTimeout(LLMUnavailable)` is raised in `OllamaClient._post`, and the existing
`except LLMUnavailable` branch in `decide_pending` stops the run. There are 3 low findings, none of
them blocking. The approval's conditions were met: the `CLAUDE.md` line was edited only after the
developer's OK on 2026-11-28, the change was built first in parallel with failure-screenshots at
the developer's request, and the spec and plan did not change after `dba1e52`.

## 2. Acceptance criteria
| AC | Result | Evidence |
|---|---|---|
| AC-C1 Timeout is a stop-the-run error | pass | `src/jobbot/llm/client.py` `_post`: `except httpx.TimeoutException` → `LLMTimeout` (a subclass of `LLMUnavailable`). `tests/test_llm_client.py::test_timeout_raises_llm_timeout` is parametrised over Read/Connect/Write/Pool timeouts. |
| AC-C2 Timeout message | pass | The message names the model, `timeout_s` and the hint (`jobbot --model`, `llm.timeout_s`). The same test asserts these, and `test_cli_llm_errors.py::test_decide_timeout_while_profiling_exits_1` checks `"Ollama timed out after 12.5s (model test-model:1b)."` with non-default values. |
| AC-C3 Timeout on a later attempt | pass | `test_timeout_on_second_attempt_after_invalid_json` and `test_timeout_on_no_think_retry`. `chat_json` catches only `ValidationError`, so a timeout is never turned into "invalid JSON after 2 attempts". |
| AC-C4 Invalid JSON is still per-job | pass | `test_invalid_json_twice_is_per_job_error` (an `LLMError`, not `LLMUnavailable`); `test_connect_error_is_unavailable` and `test_non_200_is_unavailable` (regression). |
| AC-C5 The run stops on the first timeout | pass | `tests/test_db_pipeline.py::test_decide_pending_stops_on_timeout` uses the real `LLMTimeout` class. |
| AC-C6 No job touched by the stop | pass | The same test checks counts, NULL fields and `to_decide()` order. |
| AC-C7 Per-job failure unchanged | pass | `test_decide_pending_sets_statuses` is unchanged and passes. The new `test_decide_pending_marks_failed_on_client_invalid_json` passes. |
| AC-C8 CLI output on a timeout stop | pass | `test_cli_llm_errors.py::test_decide_stops_on_timeout_with_hint` checks exit code 0, the `[1/3] ... -> pending_review` line, `Decided 1`, exactly one `Stopped` line containing the message, and no `-> failed`. |
| AC-C9 Timeout before any job | pass | `test_decide_timeout_while_profiling_exits_1`: `Error:` line, exit 1, and counts unchanged. |
| AC-C10 Other commands keep `Error:` | pass | `test_resumes_index_timeout_exits_1`. `match` and `eval` were checked by inspection: `cli.py:185` and `cli.py:236` catch `(ConfigError, LLMError, ValueError)` and call `_fail`, so they get the new message unchanged. |
| AC-C11 Docs match the code | pass | Grep for `timeout` / `timed out` / `LLMUnavailable` in the job-store and resume-matcher specs, `architecture/*.md`, `.claude/rules/llm.md` and `CLAUDE.md` found no line that still calls a timeout a per-job failure. Both changelogs have an entry. `CLAUDE.md` (the `decide_pending` bullet) was updated after the developer's OK. |
| AC-C12 Suite and lint pass without Ollama | pass (by construction) | The full suite passes: 143 tests at `d3aafe1`, including this change's 15 new ones. Ruff is clean. Ollama **was running** during the review (`/api/version` → 0.40.18), but every `OllamaClient` in the tests is built with `httpx.MockTransport` (`tests/conftest.py:69`, `tests/test_cli_llm_errors.py:63`), so no test can reach it. |

**Summary:** 12 pass, 0 fail, 0 not verified. The `scan --decide` path was checked by inspection only (see F-3).

## 3. Findings
| # | Severity | File:line | Finding | Suggested fix |
|---|---|---|---|---|
| F-1 | low | `src/jobbot/cli.py:417` | A timeout stop prints `Stopped - LLM unavailable: Ollama timed out after ...`. The label says "unavailable" while the message says "timed out". It isn't wrong, since `LLMTimeout` is an `LLMUnavailable`, but it reads oddly. This was a stated plan assumption. | Optional: print `Stopped - LLM timed out:` when `stats.aborted` came from an `LLMTimeout` (keep the exception type in `DecideStats`). A small follow-up; it changes AC-C8's expected text. |
| F-2 | low | `tests/test_llm_client.py:9`, `tests/test_cli_llm_errors.py:7` | Test helpers are imported with `from conftest import ...`. This works only because pytest's default `prepend` import mode puts `tests/` on `sys.path`, and conftest isn't meant to be imported. It also doesn't match the sibling change, which put its fakes in `tests/fakes.py`. | Move `Echo`, `ScriptedHandler`, `ask` and `chat_answer` into `tests/llm_fakes.py`, keep only fixtures in `conftest.py`, and update both imports. |
| F-3 | low | `src/jobbot/cli.py` (the `scan --decide` path) | `scan --decide` reaches the same `_run_decide` as `decide`, so it gets the new stop behaviour, but no test covers it. It opens a real browser. | Leave as is, or add a `CliRunner` test that monkeypatches `IndeedScanner.run` and `_build_matcher`, as `tests/test_cli_scan.py` does for scans. |

No critical, high or medium findings.

## 4. Checklist
- [x] Safety rules hold: no auto-submit, local-only, headed browser, no scripted login/CAPTCHA bypass, no invented form facts (none of these are touched; the LLM is still local-only through Ollama)
- [x] Untrusted input handled: the LLM output path is unchanged (schema + pydantic, retry once, then fail); the error text is escaped when printed (`escape(stats.aborted)`); the timeout message has no `[`, so `_fail` can't misrender it
- [x] Schema changes are migration files: none needed (no DB change)
- [x] Prompts changed only in `llm/prompts.py` with a version bump: no prompt change
- [x] Indeed selectors only in `platforms/indeed/parse.py`: not touched
- [x] No personal data or secrets in the diff
- [x] Tests added/updated and **run** (section 5)
- [x] `jobbot eval` run if matching or prompts changed: not needed (no prompt or matching change)
- [x] Docs updated: both specs and changelogs, `architecture/data.md`, `overview.md`, `.claude/rules/llm.md`, `CLAUDE.md`
- [x] No unrelated changes: `1d6f6fe` touches only the client, pipeline docstrings, tests and the docs listed in the plan (plus 3 stale as-built plan lines found by the AC-C11 grep, noted in the implementation report)

## 5. Commands run
```
.venv\Scripts\python -m pytest -q tests/test_llm_client.py tests/test_cli_llm_errors.py tests/test_db_pipeline.py  -> 27 passed in 1.03s
.venv\Scripts\python -m pytest -q          -> 143 passed in 2.52s
.venv\Scripts\ruff check src tests         -> All checks passed!
.venv\Scripts\ruff format --check src tests -> 37 files already formatted
curl http://localhost:11434/api/version    -> {"version":"0.40.18"}  (Ollama running; tests use MockTransport)
```

Mistakes log: F-3 is a recurrence of **M-002**: a changed path shipped with no test. It was
first missed in this review and corrected during remediation: `Seen` went to 2× and the streak reset. M-003 was applied correctly.

## 6. Remediation
Filled in by `/remediate-review`.

| # | Resolution | Notes |
|---|---|---|
| F-1 | resolved | The developer approved the label change in chat on 2026-11-28. This changes the plan's stated assumption that the label would stay. `DecideStats.timed_out` is set in `pipeline.py` from `isinstance(e, LLMTimeout)`, and `cli._run_decide` prints `Stopped - LLM timed out:` or `Stopped - LLM unavailable:`. Tests: `test_cli_llm_errors.py::test_decide_stops_on_timeout_with_hint` (asserts the new label), the new `::test_decide_unavailable_stop_keeps_unavailable_label` (regression), and `test_db_pipeline.py` (`timed_out` true on a timeout, false on unavailable). The job-store spec row for an Ollama timeout was updated. |
| F-2 | resolved | Plain helpers moved to the new `tests/llm_fakes.py` (`Echo`, `chat_answer`, `ScriptedHandler`, `ask`), matching `tests/fakes.py`. `conftest.py` keeps only the fixtures. `test_llm_client.py` and `test_cli_llm_errors.py` now import from `llm_fakes`. |
| F-3 | resolved | New `test_cli_llm_errors.py::test_scan_decide_stops_on_timeout`: `scan --decide` with a faked browser and scanner stops on the timeout, with exit 0, the `Stopped - LLM timed out:` line, no `-> failed` line, and counts `{pending_review: 1, new: 2}`. |

Remediation commands (2026-11-28):
```
pytest -q tests/test_llm_client.py tests/test_cli_llm_errors.py tests/test_db_pipeline.py tests/test_cli_scan.py  -> 35 passed
ruff check / format --check on the changed files  -> All checks passed! / 5 files already formatted
pytest -q (full suite)  -> 146 passed, 1 failed (tests/test_indeed_scanner.py::test_json_empty_on_first_page_snapshots_and_skips_search)
```
The full-suite failure and one ruff E501 (`src/jobbot/platforms/indeed/scanner.py:8`) come from
uncommitted failure-screenshots work by another session that was in progress during this
remediation. They are not part of this change, and those files were not touched here.
