# Implementation plan: job-store / llm-timeout-stops-run

> Lane B: `features/job-store/changes/llm-timeout-stops-run/implementation-plan.md`

| | |
|---|---|
| Spec / request | [change-definition.md](change-definition.md) (AC-C1..AC-C12), [request.md](request.md); capability specs: [job-store](../../specification.md), [resume-matcher](../../../resume-matcher/specification.md) |
| Author | AI agent |
| Date | 2026-11-27 |
| Base commit | `fc9e8e9` (working tree also has the uncommitted docs for this change and the two indeed-scanner changes; no source changes) |
| Approval | Not yet. The developer writes `plan-approval.md` by hand. |
| Mistakes log | M-002 (every new error path gets a test), M-003 (choose each error type by its effect on the whole run; test both sides), M-001 (docs match the code) |

## 1. What I understood
Today `OllamaClient._post` turns any `httpx.TimeoutException` into a plain `LLMError`
(`llm/client.py:105-106`), so `decide_pending` marks that job `failed` and moves on
(`pipeline.py:46-52`). With a stuck model, each job waits up to `llm.timeout_s` (600 s) and fails
in turn. After this change a timeout of any kind (connect, read, write, pool) on any attempt of a
call is a **stop-the-run** error: the client raises a new `LLMTimeout`, a subclass of
`LLMUnavailable`. The existing `except LLMUnavailable` branch in `pipeline.py:43-45` then stops the
run, and the current job and all later jobs stay `new`. There is no retry after a timeout. The
message names the model, the timeout value and a hint (smaller model via `--model`, or a larger
`llm.timeout_s`). Invalid JSON after the one retry stays a per-job `LLMError` that marks only that
job `failed`. Every CLI command that catches `LLMError` keeps working unchanged and shows the new
message. All four open questions were resolved by the developer on 2026-11-27 (change-definition
§7): `resumes index` keeps stopping with the new message, `timeout_s` stays 600, a stopped decide
run exits 0, and the "job that always times out" risk is accepted.

## 2. Affected layers
| Layer | Impact | Notes |
|---|---|---|
| DB (migrations) | **none** | No schema, status, index or constraint change. No migration file. Latest migration stays `0001_init.sql`. Existing rows are not rewritten (jobs that became `failed` through a timeout earlier stay `failed`; `--retry-failed` re-queues them as today). |
| Core logic (`matcher/`, `pipeline.py`, `llm/`, `resumes/`, `platforms/`) | yes | `llm/client.py`: new `LLMTimeout(LLMUnavailable)`, the timeout message with the hint, an optional `transport` argument (test seam). `pipeline.py`: docstring and one comment only, **no logic change**. `matcher/`, `resumes/`, `platforms/`: no change. |
| Interface (CLI `cli.py`, dashboard) | behaviour only, **no code change** | `decide` / `scan --decide` now stop on a timeout with the existing `Stopped - LLM unavailable: <msg>` line (the message itself says "Ollama timed out ..."). `resumes index`, `match`, `eval` and the profiling step of `decide` print the new message through the existing `except LLMError` -> `Error:` path, exit 1. Exit code of a stopped decide run stays 0 (OQ-3). No new command or flag. No dashboard yet. |
| Config (`config.py`, `config/*.yaml`, `profile.yaml`) | none | `llm.timeout_s` keeps its meaning and its default of 600 (OQ-2). No new key; `settings.example.yaml` unchanged. |
| Prompts (`llm/prompts.py`, version bump?) | none | No prompt or schema change, no version bump. `jobbot eval` before/after is **not required** (no matching change). |
| Safety rules (`CLAUDE.md`) | none weakened | See the safety table below. The bot does less when the model is stuck. |
| Tests | yes | New `tests/conftest.py`, `tests/test_llm_client.py`, `tests/test_cli_llm_errors.py`; two new tests in `tests/test_db_pipeline.py`. All run in the default `pytest` (no `-m llm`, no Ollama, no network, `tmp_path` only). |
| Docs | yes | Both specs + both changelogs, `architecture/data.md`, `architecture/overview.md`, `.claude/rules/llm.md`; `CLAUDE.md:106` only with the developer's OK (see §4.4). |

### Safety rules (`.claude/rules/safety.md`)
| Rule | How it is kept |
|---|---|
| 1. Never auto-submit | Untouched. No browser, form or submit code changes. |
| 2. Everything stays local | No new network destination. The `transport` argument defaults to `None` (httpx's normal transport to `llm.base_url`); only tests pass an in-memory `httpx.MockTransport`. Calls stay sequential (ADR-0001). |
| 3. Protect the Indeed account | Untouched. `scan` itself makes no LLM call; `scan --decide` only changes after the scan has finished. |
| 4. Personal data gitignored | Tests use `tmp_path` for `data_dir`/DB and synthetic job text; no real `data/`, `resumes/`, `profile.yaml`. The error message contains only the model name, a number and a static hint. |
| 5. Never invent facts | Untouched (no form filling). |
| 6. Untrusted input | Untouched. LLM output is still validated by schema + pydantic; the new message is built from settings, not from LLM or scraped text. |
| 7. Approval files | This plan does not create `plan-approval.md`; implementation must not either. |

## 3. Database changes
None. No migration file, no table/column/index/constraint change, no status added, renamed or
removed, no data rewrite. `data/decisions.jsonl` and `data/resume_profiles.json` are unchanged
(timed-out calls were never logged and still are not; resume-matcher OQ-7 stays open).

| Migration file | Change | Reversible? |
|---|---|---|
| (none) | - | - |

## 4. Module interfaces and CLI commands

### 4.1 `src/jobbot/llm/client.py`
1. **New exception**, defined right after `LLMUnavailable`:
   ```python
   class LLMTimeout(LLMUnavailable):
       """An Ollama call timed out (connect, read, write or pool). Treated like
       LLMUnavailable: the model is almost always stuck, still loading or too slow,
       so callers stop instead of failing every remaining job. No retry."""
   ```
   It is a subclass of `LLMUnavailable` (so `pipeline.py:43` stops the run with no new branch)
   and therefore of `LLMError` (so every CLI `except LLMError` still catches it).
2. **`LLMUnavailable` docstring** updated to list "or a call timed out (`LLMTimeout`)" (R-1).
3. **Constructor seam** (A-4), keyword-only, default keeps production behaviour identical:
   ```python
   def __init__(self, settings: LLMSettings, *, transport: httpx.BaseTransport | None = None) -> None:
       self.settings = settings
       self._http = httpx.Client(
           base_url=settings.base_url, timeout=settings.timeout_s, transport=transport
       )
   ```
   `httpx.Client(transport=None)` is httpx's default (verified in the scratchpad on httpx 0.28.1:
   it builds the normal `HTTPTransport`; a `MockTransport` handler that raises `httpx.PoolTimeout`
   propagates as `httpx.TimeoutException` out of `Client.post`). No caller passes `transport`
   in production code. No new dependency (`MockTransport` ships with httpx).
4. **`_post` timeout branch** (`client.py:105-106`) becomes:
   ```python
   except httpx.TimeoutException as e:
       raise LLMTimeout(
           f"Ollama timed out after {s.timeout_s:g}s (model {s.model}). The model may be stuck,"
           " still loading or too slow for this machine. Try a smaller model"
           " (jobbot --model <name> ...) or a larger llm.timeout_s in config/settings.yaml."
       ) from e
   ```
   - Covers `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout` (all subclasses of
     `httpx.TimeoutException`; `ConnectTimeout` is **not** a subclass of `ConnectError`, checked
     via its MRO on httpx 0.28.1, so the `except httpx.ConnectError` branch above does not catch it
     and the branch order does not matter).
   - `{s.timeout_s:g}` prints `600s` / `12.5s` instead of today's `600.0s`.
   - The message must contain **no `[`** characters: `cli._fail` prints `str(e)` inside Rich
     markup without `escape` (`cli.py:53`). The CLI tests (§6) assert the message appears verbatim
     in the output, which guards this.
   - The no-`think` retry (`client.py:107-110`) calls `self._post` recursively, so a timeout there
     goes through the same branch (AC-C3).
   - `chat_json` needs **no change**: a timeout on attempt 2 (after invalid JSON on attempt 1)
     propagates out of `_post` before the "invalid JSON after 2 attempts" `LLMError` is built
     (AC-C3). There is no retry after a timeout (BR-C2).
5. Unchanged: `ConnectError -> LLMUnavailable`, non-200 -> `LLMUnavailable`, invalid JSON twice ->
   plain `LLMError`.

### 4.2 `src/jobbot/pipeline.py` (comments only)
- `DecideStats.aborted` comment: "set when the LLM became unavailable or timed out".
- `decide_pending` docstring: "If Ollama is unavailable **or a call times out**, the run stops,
  leaving the current and remaining jobs 'new' for next time."
- No logic change: `except LLMUnavailable` (line 43) now also receives `LLMTimeout`; `except
  LLMError` (line 46) now only receives non-unavailable errors (invalid JSON).

### 4.3 `src/jobbot/cli.py`
No code change. Behaviour per command (exceptions as they reach the CLI):

| Command | Path | Before | After |
|---|---|---|---|
| `decide`, `scan --decide` (job loop) | `_run_decide` -> `decide_pending` | each timed-out job `-> failed: ...`, run continues | run stops; `Decided N (...)`, then `Stopped - LLM unavailable: Ollama timed out after ... <hint>`; exit 0 |
| `decide`, `scan --decide` (profiling in `_build_matcher`) | `cli.py:392` `except LLMError` | `Error: Ollama timed out ...`, exit 1 | same, message with hint |
| `resumes index` | `cli.py:78` | `Error: ...`, exit 1 | same, message with hint |
| `match` | `cli.py:179` | `Error: ...`, exit 1 | same, message with hint |
| `eval` | `cli.py:230` | `Error: ...`, exit 1 (aborts eval) | same, message with hint |

The stop-line label stays `Stopped - LLM unavailable:` (AC-17 of the job-store spec unchanged);
the message after it says "timed out", so no type check is needed in the CLI.

### 4.4 Every caller of `LLMError` / `LLMUnavailable` (grep of `src/` and `tests/`, base `fc9e8e9`)
| Place | Catches / uses | Checked effect |
|---|---|---|
| `src/jobbot/pipeline.py:10, 43-45` | `except LLMUnavailable` -> `stats.aborted`, `break` | Now also gets `LLMTimeout`: intended (BR-C1). |
| `src/jobbot/pipeline.py:46-52` | `except LLMError` -> `mark_failed`, continue | No longer gets timeouts; still gets invalid JSON (BR-C3). |
| `src/jobbot/cli.py:27, 78` (`resumes index`) | `except (ConfigError, LLMError)` | Same exit path; new message. |
| `src/jobbot/cli.py:179` (`match`) | `except (ConfigError, LLMError, ValueError)` | Same; new message. |
| `src/jobbot/cli.py:230` (`eval`) | same tuple | Same; new message. |
| `src/jobbot/cli.py:392` (`_run_decide`) | same tuple, around `_build_matcher` + `decide_pending` | `decide_pending` swallows `LLMTimeout` into `stats.aborted`; only a profiling timeout reaches this `except`. |
| `src/jobbot/resumes/profiler.py`, `src/jobbot/matcher/decide.py`, `src/jobbot/platforms/` | no catch; exceptions propagate | Unchanged. `Matcher.decide` logs only successful decisions. |
| `tests/test_db_pipeline.py:4, 103, 119` | raise `LLMError("bad json")`, `LLMUnavailable("out of memory")` via `FakeMatcher` | Unaffected; keep passing unchanged. |

The implementer re-runs `grep -rn "LLMError\|LLMUnavailable\|TimeoutException" src tests` before
coding and stops if a new caller appeared since `fc9e8e9`.

## 5. Dashboard screens (if any)
None (dashboard not built).

## 6. Test plan
All tests run in the default `.venv\Scripts\python -m pytest` (no `@pytest.mark.llm`), with no
Ollama, no network and no real `data/`. Baseline at `fc9e8e9` (run 2026-11-27):
`85 passed in 1.55s`; `ruff check` "All checks passed!"; `ruff format --check` "30 files already
formatted".

**Shared fixtures, new `tests/conftest.py`:**
- `Echo(BaseModel)`: `ok: bool`, a tiny output model for `chat_json`.
- `llm_settings`: `LLMSettings(model="test-model:1b", timeout_s=12.5)` (non-default values, so the
  AC-C2 asserts can't pass on defaults; `think` stays `"low"` so the no-`think` path is reachable).
- `make_client(handler, settings=None) -> OllamaClient`: builds
  `OllamaClient(settings or llm_settings, transport=httpx.MockTransport(handler))` and closes all
  clients at teardown.
- `timeout_error -> LLMTimeout`: the **real** exception produced by a client whose handler raises
  `httpx.ReadTimeout(..., request=request)`.
- `invalid_json_error -> LLMError`: the real "invalid JSON after 2 attempts" error from a client
  whose handler always answers `200 {"message": {"content": "not json"}}`.
- Handlers record each request (`calls` list) so tests can assert the number of HTTP attempts.

**CLI tests (`tests/test_cli_llm_errors.py`) setup** via `monkeypatch` + `typer.testing.CliRunner`:
- `cli.load_settings` -> `Settings(llm=llm_settings, data_dir=tmp_path, resumes_dir=tmp_path / "resumes", config_dir=tmp_path / "config")`; the DB is `tmp_path / "jobs.db"`, seeded with `JobStore` before invoking.
- `cli.console` -> `Console(width=400, color_system=None)` so long messages don't wrap and no ANSI codes appear (the module `console` is looked up at call time; Rich resolves `sys.stdout` at print time, so `CliRunner` captures it).
- For AC-C9/AC-C10: `cli.OllamaClient` -> a factory returning `OllamaClient(s, transport=MockTransport(<raises ReadTimeout>))`; `cli.load_library` -> a stub with `resumes=[]`; `cli.build_profiles` -> a function that calls `client.chat_json(system="s", user="u", output_model=Echo)`. This runs the real `_build_matcher` / `resumes_index` code and the real client, so the message comes from production code.
- For AC-C8: `cli._build_matcher` -> a small scripted matcher (same shape as `FakeMatcher` in `test_db_pipeline.py`, defined locally) that decides `a` and raises `timeout_error` for `b`.

| AC | Test (file::name) or check | Needs LLM? |
|---|---|---|
| AC-C1 timeout is stop-the-run | `tests/test_llm_client.py::test_timeout_raises_llm_timeout` parametrized over `ReadTimeout`, `ConnectTimeout`, `WriteTimeout`, `PoolTimeout`: raises `LLMTimeout`, `isinstance` of `LLMUnavailable` and `LLMError`, `__cause__` is the httpx exception, handler called **exactly once** (no retry, BR-C2) | no |
| AC-C2 message | same test: message contains `test-model:1b`, `12.5s`, `--model`, `llm.timeout_s`, and no `[` | no |
| AC-C3 timeout on a later attempt | `tests/test_llm_client.py::test_timeout_on_second_attempt_after_invalid_json` (1st: 200 + `not json`, 2nd: `ReadTimeout` -> `LLMTimeout`, not "invalid JSON", 2 calls); `tests/test_llm_client.py::test_timeout_on_no_think_retry` (1st: 400 "model does not support thinking", 2nd: `ReadTimeout` -> `LLMTimeout`; 2nd request body has no `think`) | no |
| AC-C4 invalid JSON still per-job; other errors still unavailable | `tests/test_llm_client.py::test_invalid_json_twice_is_per_job_error` (`LLMError`, **not** `LLMUnavailable`, message "invalid JSON after 2 attempts", 2 calls); `::test_connect_error_is_unavailable` (`httpx.ConnectError` -> `LLMUnavailable`, not `LLMTimeout`); `::test_non_200_is_unavailable` (500 -> `LLMUnavailable`, not `LLMTimeout`) | no |
| (seam sanity, supports AC-C1..C4 and R-5) | `tests/test_llm_client.py::test_valid_answer_returns_parsed_model`: a valid answer returns `Echo(ok=True)` with `LLMCallInfo.model == "test-model:1b"`, `attempts == 1`; request went to `/api/chat` with `format` and `stream: False` | no |
| AC-C5 run stops on first timeout | `tests/test_db_pipeline.py::test_decide_pending_stops_on_timeout`: jobs `a,b,c`, `FakeMatcher` decides `a`, raises `timeout_error` for `b`; asserts `matcher.calls == ["a", "b"]`, `decided == 1`, `failed == 0`, `stats.aborted == str(timeout_error)`, `on_decision` recorded only job `a` | no |
| AC-C6 no job touched by the stop | same test: `store.counts() == {"pending_review": 1, "new": 2}`; rows `b`, `c` have `error`, `decision`, `decided_at` NULL; `[r["job_key"] for r in store.to_decide()] == ["b", "c"]` | no |
| AC-C7 per-job failure unchanged | existing `tests/test_db_pipeline.py::test_decide_pending_sets_statuses` (unchanged) + new `tests/test_db_pipeline.py::test_decide_pending_marks_failed_on_client_invalid_json` (`FakeMatcher` raises `invalid_json_error` for `b`; `b` is `failed` with that error text, `c` is still decided, `aborted is None`) | no |
| AC-C8 CLI output on a timeout stop | `tests/test_cli_llm_errors.py::test_decide_stops_on_timeout_with_hint`: exit code 0; output has `[1/3] Java Developer @ Acme -> pending_review`, `Decided 1 (pending_review: 1)`, a line starting `Stopped` containing `str(timeout_error)`; no `-> failed`; DB counts `{"pending_review": 1, "new": 2}` | no |
| AC-C9 timeout before any job | `tests/test_cli_llm_errors.py::test_decide_timeout_while_profiling_exits_1`: exit code 1; output `Error: Ollama timed out after 12.5s (model test-model:1b)...` with the hint; `store.counts()` equal before and after (`{"new": 2}`) | no |
| AC-C10 other commands keep `Error:` | `tests/test_cli_llm_errors.py::test_resumes_index_timeout_exits_1`: exit code 1, `Error:` + full timeout message. `match` / `eval`: same `except LLMError` pattern (`cli.py:179, 230`), checked by inspection in the review | no |
| A-3 `scan --decide` | inspection: `scan` calls the same `_run_decide` (`cli.py:353-354`); not tested because `scan` opens a browser (no browser in tests) | no |
| AC-C11 docs match the code | review grep: `grep -rn -i "timeout\|timed out\|LLMUnavailable\|LLMTimeout" documentation/ .claude/rules/ CLAUDE.md` and check each hit (M-001) | no |
| AC-C12 suite and lint pass without Ollama | `.venv\Scripts\python -m pytest`, `.venv\Scripts\ruff check src tests`, `.venv\Scripts\ruff format --check src tests`, run with Ollama stopped; output pasted in `review.md` | no |

**Count:** 12 new test functions (15 collected items, because AC-C1 is parametrized 4 ways), in
3 new files plus 2 new tests in `tests/test_db_pipeline.py`. Expected total: **100 passed**
(85 + 15). No existing test changes.

## 7. Implementation steps
Precondition: `plan-approval.md` written by the developer exists in this folder (checked by
`/implement-feature`).

1. Re-check the base: `git rev-parse --short HEAD`, re-run the §4.4 grep, run the baseline
   `pytest` / `ruff check` / `ruff format --check` and note the results.
2. `src/jobbot/llm/client.py`: add `LLMTimeout(LLMUnavailable)`; update the `LLMUnavailable`
   docstring; add the keyword-only `transport` argument; raise `LLMTimeout` with the hint in the
   `httpx.TimeoutException` branch (§4.1).
3. `src/jobbot/pipeline.py`: update the `decide_pending` docstring and the `DecideStats.aborted`
   comment (§4.2). No logic change.
4. `tests/conftest.py`: add `Echo`, `llm_settings`, `make_client`, `timeout_error`,
   `invalid_json_error` (§6).
5. `tests/test_llm_client.py`: AC-C1..AC-C4 tests plus the seam sanity test.
6. `tests/test_db_pipeline.py`: add `test_decide_pending_stops_on_timeout` and
   `test_decide_pending_marks_failed_on_client_invalid_json`.
7. `tests/test_cli_llm_errors.py`: AC-C8, AC-C9, AC-C10 tests.
8. Run `.venv\Scripts\ruff format src tests`, then the three verification commands (below); fix
   until all pass (expected `100 passed`).
9. Docs (same change, AC-C11):
   - `features/job-store/specification.md`: §2 actors row (line 32: timeouts are "unavailable");
     BR-9 (timeouts stop the run, no retry, message with hint) and BR-10 (invalid JSON only),
     with references `llm/client.py` `LLMTimeout`; §6 T-8 and T-10 triggers; §9 rows (lines
     167-168: a timeout now stops the run; per-job row is invalid JSON only); AC-10 (narrowed to
     non-`LLMUnavailable` errors) and AC-11 (includes timeouts), each with its new test name; §11
     OQ-2 marked resolved by this change; §12 dependency row (`LLMTimeout`).
   - `features/job-store/changelog.md`: new entry "2026-11-27: Ollama timeouts stop the decide
     run. See changes/llm-timeout-stops-run/."
   - `features/resume-matcher/specification.md`: §10 error rows (lines 261-262: `LLMUnavailable`
     includes `LLMTimeout`; `LLMError` is invalid JSON only); line 236 (`LLMUnavailable`, including
     timeouts, stops the run); AC-28 (a timeout raises `LLMTimeout`, an `LLMUnavailable`; replace
     the "Gap: no automated test" note with the `tests/test_llm_client.py` test names); OQ-3
     resolved.
   - `features/resume-matcher/changelog.md`: new entry for the client contract change.
   - `architecture/data.md:70`: `failed` = invalid LLM output after one retry; `LLMUnavailable`
     (including timeouts) does not mark jobs, the run stops.
   - `architecture/overview.md:67-68`: `pipeline.py` row (timeouts stop the run) and
     `llm/client.py` row (`LLMError` / `LLMUnavailable` / `LLMTimeout`).
   - `.claude/rules/llm.md:8`: "`LLMUnavailable` (Ollama down, OOM, HTTP error, **timeout**)
     stops the run."
   - `README.md`: does not exist at `fc9e8e9`; nothing to update (no command or flag change).
10. **Ask the developer** before editing `CLAUDE.md:106` (the `decide_pending` bullet). Proposed
    text: "an `LLMUnavailable` error (Ollama down / OOM / HTTP error / **timeout**, raised as
    `LLMTimeout`) **stops the run** and leaves jobs `new`. A per-job `LLMError` (bad JSON) marks
    just that job `failed`; ...". Edit only on an explicit OK; otherwise record it as an open item
    in `review.md`.
11. Self-review the diff against AC-C1..AC-C12 and the AC-C11 grep; update
    `.claude/mistakes/common-mistakes.md` (M-002 and M-003 situations came up: add to the clean
    streak if avoided; consider deleting M-003 if the new tests are judged an automated guard, and
    say so in the report). Then `/review-feature job-store/changes/llm-timeout-stops-run`.

**Verification commands** (Windows, repo root; paste the summary lines in `review.md`):
```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
```

**Build order:** this change goes **first**. It is independent of the two indeed-scanner changes
(`indeed-scanner/changes/scan-cap-and-paging`, `indeed-scanner/changes/failure-screenshots`): it
touches `llm/client.py`, `pipeline.py` docstrings and new tests, not `platforms/indeed/`,
`browser.py` or `scanner.py`. The only shared files are `cli.py` (not edited here) and possibly
the job-store/indeed-scanner docs; if a later change edits the same doc lines, it rebases on this
one.

## 8. Risks
- **R-1 Wider meaning of `LLMUnavailable`.** Any future `except LLMUnavailable` also gets
  timeouts. Mitigation: the `LLMUnavailable` and `LLMTimeout` docstrings say so; §4.4 lists every
  current caller (only `pipeline.py:43`, the intended one).
- **R-2 A one-off slow call now stops a run** that used to fail one job and continue. With a 600 s
  budget this needs a really stuck call; the user reruns `jobbot decide` and no job is lost or
  marked `failed`.
- **R-3 Poison job** (OQ-4): a job that always times out stops every run at the same place.
  Accepted by the developer on 2026-11-27; revisit only if seen.
- **R-4 Doc drift (M-001).** Seven doc locations plus `CLAUDE.md` describe timeouts as per-job
  failures; step 9 lists each, and AC-C11's grep checks them.
- **R-5 Test seam changes production behaviour.** Mitigated: `transport` is keyword-only, defaults
  to `None` (httpx's own default), and production callers don't pass it;
  `test_valid_answer_returns_parsed_model` exercises the normal success path through the seam.
- **R-6 Rich markup in `_fail`.** `cli._fail` prints the message without `escape`, so a `[` in
  the timeout message would be eaten. Mitigated by keeping `[` out of the message; the CLI tests
  compare the full message verbatim. (The unescaped `_fail` itself is existing debt, out of
  scope; related to resume-matcher OQ-13.)
- **R-7 Console wrapping in CLI tests.** Rich wraps at 80 columns under `CliRunner`, which would
  break substring asserts. Mitigated by patching `cli.console` with a wide, colourless console.
- **R-8 Message format change.** `{timeout_s:g}` gives `600s` instead of `600.0s`. Old `failed`
  rows keep the old text; nothing parses this text.

## 9. Open questions and assumptions
- **No open questions.** OQ-1..OQ-4 of the change definition were decided by the developer in
  chat on 2026-11-27 (all recommendations accepted) and are recorded in change-definition.md §7.
- **Needs the developer's OK at implementation time:** editing `CLAUDE.md:106` (step 10).
- **A-1 (final choice):** the client raises a new `LLMTimeout(LLMUnavailable)`; the pipeline and
  CLI need no new branch.
- **A-4 (final choice):** the test seam is a keyword-only `transport: httpx.BaseTransport | None =
  None` argument on `OllamaClient.__init__` (rather than replacing the private `_http` in tests).
- **Assumption:** the stop-line label in `_run_decide` stays `Stopped - LLM unavailable:` (no CLI
  code change); the message itself says "Ollama timed out". If the developer prefers a distinct
  label (e.g. `Stopped - LLM timed out:`), that needs a type-aware `aborted` field and is a
  separate small change.
- **Out of scope** (unchanged, tracked elsewhere): lost partial profiling progress
  (resume-matcher OQ-9), logging of failed calls (OQ-7), unescaped Rich markup (OQ-13), a non-zero
  exit code for stopped runs.

## 10. ADRs needed
- None. This follows the existing consequence in
  [ADR-0001](../../../../decisions/ADR-0001-local-only-llm.md) ("`LLMUnavailable` stops the run
  instead of failing every job") and changes no architecture, dependency, data or safety rule.
- Related: ADR-0001 (local-only LLM, sequential calls, the stop-the-run consequence); ADR-0003
  (SQL migrations: none needed here); ADR-0004 (human approval: untouched).
