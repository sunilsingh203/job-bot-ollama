# Change definition: job-store / llm-timeout-stops-run

> Lane B. Path: `documentation/development/features/job-store/changes/llm-timeout-stops-run/change-definition.md`.

| | |
|---|---|
| Capability | `job-store` ([specification.md](../../specification.md)); also touches `resume-matcher` ([specification.md](../../../resume-matcher/specification.md), `llm/client.py`) |
| Status | **Draft.** Open questions resolved 2026-11-27 (developer in chat, all recommendations accepted); awaiting plan approval |
| Date | 2026-11-27 |
| Request | [request.md](request.md), including "Decisions (2026-11-27, developer in chat)" |
| Mistakes log | M-003 (pick the error type by its effect on the whole run; write the choice down; test both cases) |

Code references are to the working tree on branch `docs/spec-driven-workflow` (after commit
`fc9e8e9`). Nothing in this document changes code.

---

## 1. Current behaviour

### 1.1 How the LLM client classifies errors (`src/jobbot/llm/client.py`)
- Two exception types: `LLMError(RuntimeError)` (`client.py:17-18`) and its subclass
  `LLMUnavailable(LLMError)` (`client.py:21-23`). The docstring of `LLMUnavailable` says
  "Retrying other jobs is pointless; callers should stop."
- The HTTP client is built once with `httpx.Client(base_url=..., timeout=settings.timeout_s)`
  (`client.py:38`). `llm.timeout_s` defaults to `600` (`config.py:30`,
  `config/settings.example.yaml:9`). httpx applies that value separately to the connect, read,
  write and pool phases; it is not a total deadline. With `stream: False`, the read timeout means
  "no response bytes for 600 s".
- `_post` (`client.py:97-113`) maps transport errors:
  - `httpx.ConnectError` -> `LLMUnavailable("Cannot reach Ollama at ... Is it running?")` (`client.py:101-104`)
  - `httpx.TimeoutException` (any of `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`,
    `PoolTimeout`; checked against installed httpx 0.28.1) ->
    **plain `LLMError("Ollama timed out after {timeout_s}s (model {model}).")`** (`client.py:105-106`).
    There is no hint in the message.
  - HTTP 400 mentioning "thinking" while `think` was sent -> retried once without `think`
    (`client.py:107-110`); a timeout in that retry is also a plain `LLMError`.
  - Any other non-200 status -> `LLMUnavailable("Ollama error <code>: ...")` (`client.py:111-112`).
- `chat_json` (`client.py:49-95`) calls `_post` up to 2 times. On invalid JSON it retries once
  (`client.py:78-87`); after 2 invalid answers it raises a plain
  `LLMError("Model returned invalid JSON after 2 attempts: ...")` (`client.py:95`). A timeout on
  either attempt propagates straight out of `_post` as the plain `LLMError` above.

### 1.2 How `decide_pending` reacts (`src/jobbot/pipeline.py`)
- `except LLMUnavailable` (`pipeline.py:43-45`): sets `stats.aborted` to the message and
  `break`s. The current job and all later jobs stay `new` (job-store BR-9, T-10, AC-11).
- `except LLMError` (`pipeline.py:46-52`): `store.mark_failed(id, str(e))`, counts the failure,
  calls `on_decision(..., None, str(e))` and **continues with the next job** (job-store BR-10,
  T-8, AC-10).
- So today a timeout lands in the second branch: the job becomes `failed` with
  `error = "Ollama timed out after 600.0s (model ...)."` and the next job is tried. With a stuck
  model, every job waits up to `timeout_s` and fails in turn (job-store OQ-2, resume-matcher OQ-3).

### 1.3 How the CLI reacts (`src/jobbot/cli.py`)
- `_run_decide` (`cli.py:370-397`), used by `jobbot decide` (`cli.py:357-367`) and
  `jobbot scan --decide` (`cli.py:353-354`):
  - per job, `on_decision` prints `[i/n] title @ company -> <status> ...` or
    `-> failed: <error>` (`cli.py:377-386`)
  - `_build_matcher(client)` (`cli.py:116-127`) calls `build_profiles` before any job; an
    `LLMError` there (including a timeout) is caught at `cli.py:392-393` -> `Error: <msg>`, exit 1,
    no job touched
  - after the loop: `Decided N (<status>: <count>, ...)` (`cli.py:394-395`) and, when
    `stats.aborted` is set, `Stopped - LLM unavailable: <msg>` (`cli.py:396-397`). **The process
    exits 0 in that case** (nothing raises).
- Other LLM commands catch the base class and stop with `Error: <msg>`, exit 1:
  `resumes index` (`cli.py:78`), `match` (`cli.py:179`), `eval` (`cli.py:230`; any `LLMError`
  already aborts the whole eval).

### 1.4 Resume profiling today (`jobbot resumes index`, request open question 2)
- `build_profiles` (`src/jobbot/resumes/profiler.py:53-111`) calls `client.chat_json` per
  resume (`profiler.py:86-90`) and does not catch anything.
- A timeout therefore raises the plain `LLMError`, which `resumes_index` catches
  (`cli.py:78-79`) -> `Error: Ollama timed out after 600.0s (model ...).`, exit 1.
- The cache file is written only at the end (`profiler.py:108-110`), so profiles built earlier
  in the same run are lost (resume-matcher OQ-9).
- **Conclusion: profiling already stops on the first timeout.** Only the message (no hint) and
  the lost partial progress differ from what this change wants for `decide`.

### 1.5 Every caller of the two exception types (grep of `src/` and `tests/`)
| Place | Catches | Effect of the change |
|---|---|---|
| `pipeline.py:43` | `LLMUnavailable` | **Changes:** timeouts now stop the run (the point of this change). |
| `pipeline.py:46` | `LLMError` | **Changes:** no longer receives timeouts; still receives invalid JSON. |
| `cli.py:78` (`resumes index`) | `LLMError` | Same behaviour (a subclass of `LLMError` is still caught); message gains the hint. |
| `cli.py:179` (`match`) | `LLMError` | Same; message gains the hint. |
| `cli.py:230` (`eval`) | `LLMError` | Same; message gains the hint. |
| `cli.py:392` (`_run_decide`, matcher build) | `LLMError` | Same; message gains the hint. |
| `tests/test_db_pipeline.py:4, 103, 119` | raise `LLMError("bad json")` / `LLMUnavailable("out of memory")` through `FakeMatcher` | Unaffected; they don't involve timeouts. |

No other module (`matcher/decide.py`, `resumes/profiler.py`, `platforms/`) catches either type.
`Matcher.decide` (`matcher/decide.py:110-112`) lets exceptions propagate and only logs
successful decisions to `data/decisions.jsonl`.

## 2. Proposed behaviour

### 2.1 Business rules (changes to the job-store spec §4)
- **BR-C1 (replaces job-store BR-9).** If the LLM is unavailable **or a call times out**, the
  `decide` run stops immediately. "Unavailable" is: Ollama unreachable, a non-200 HTTP response
  (e.g. out of memory at model load), or an httpx timeout of any kind (connect, read, write,
  pool) on any attempt of the call, including the second attempt after invalid JSON and the
  no-`think` retry. The current job and all remaining jobs stay `new`, no row is written for the
  current job, and the remaining jobs are picked up by the next run.
- **BR-C2 (developer decision 2026-11-27).** There is **no retry** after a timeout. The first
  timeout stops the run.
- **BR-C3 (replaces job-store BR-10).** A per-job `LLMError` that is not an unavailable/timeout
  error (today: invalid JSON after the existing one retry) still marks only that job `failed`,
  and the run continues. Unchanged from today apart from timeouts no longer being in this group.
- **BR-C4.** The timeout message names the model, the configured timeout value and a hint:
  try a smaller model (`jobbot --model <name>`) or a larger `llm.timeout_s` in
  `config/settings.yaml`. `jobbot decide` and `jobbot scan --decide` print it on the stop line
  after the `Decided N (...)` summary.
- **BR-C5 (unchanged, restated).** Jobs are still decided one at a time; jobs decided before
  the timeout keep their saved decisions (each write commits immediately, job-store BR-12).

### 2.2 States and transitions (job-store spec §6)
- No new status. No status is renamed or removed.
- **T-8** (`new` -> `failed`): trigger narrows to "per-job `LLMError` that is not
  `LLMUnavailable`" (invalid JSON after the retry). Timeouts no longer cause it.
- **T-10** (`new` -> `new`, run aborted): trigger widens to "`LLMUnavailable`, including
  timeouts".

### 2.3 Error cases (job-store spec §9, resume-matcher spec §10)
| Case | New behaviour |
|---|---|
| Ollama timeout while deciding job *i* | Run stops. Job *i* and later jobs stay `new` (error NULL, no decision). Jobs 1..*i-1* keep their results. CLI prints the summary, then the stop line with model, timeout value and hint. No `-> failed` line for job *i*. |
| Ollama timeout while building resume profiles inside `decide` / `scan --decide` | Unchanged: `Error: <msg>`, exit 1, no job touched. The message now carries the hint. |
| Ollama timeout in `resumes index`, `match`, `eval` | Unchanged: `Error: <msg>`, exit 1. The message now carries the hint (OQ-1, decided: `resumes index` keeps stopping on the first timeout; profiles built earlier in that run are still lost, out of scope). |
| Invalid JSON after the retry | Unchanged: that job `failed`, run continues. |
| Ollama unreachable / non-200 | Unchanged: run stops (decide) or `Error:` exit 1 (other commands). |

### 2.4 Mechanism (for the plan to confirm; see A-1)
The classification lives in the client, not the pipeline: `_post` raises an `LLMUnavailable`
(suggested: a new subclass `LLMTimeout(LLMUnavailable)`, so the CLI can label it "timed out"
and tests can assert the exact type) for `httpx.TimeoutException`. Then the existing
`except LLMUnavailable` branch in `pipeline.py:43-45` handles it with no new branch, and every
CLI `except LLMError` still catches it.

### 2.5 Permissions and safety
- The bot does nothing new on its own. The only effect is that it **does less** when the model
  is stuck (stops instead of hammering it). The human restarts the run.
- Checked against `.claude/rules/safety.md`: no conflict. No browser, Indeed, form, submit,
  network or personal-data change. LLM calls stay local (ADR-0001) and sequential. This change
  follows ADR-0001's stated consequence: "`LLMUnavailable` stops the run instead of failing
  every job".
- The change does **not** touch the DB schema, statuses, prompts, the decision schema or the
  Indeed integration. It does change shared code (`llm/client.py`), which is why it is Lane B.

## 3. Why
A timeout almost always means the model itself is stuck (too slow, out of memory, still
loading `gpt-oss:20b` on 6 GB VRAM), not that one job is bad. Per-job prompts are bounded: the
description is cut to `llm.max_jd_chars` (6,000) before the call (`matcher/decide.py:134`) and
only resume summaries are sent. Today a stuck model makes each job wait up to 600 s and then
marks it `failed`; a 50-job run can waste hours, and every job must be re-queued with
`--retry-failed`. See request.md and M-003.

## 4. Impact
| Area | Impact |
|---|---|
| Business rules (spec sections changed) | job-store: §4 BR-9 and BR-10 (-> BR-C1..C3), §6 T-8 and T-10, §9 the "Bad JSON ... or an Ollama timeout" row and the LLM-unavailable row, §10 AC-10 and AC-11 wording, §11 OQ-2 (resolved). resume-matcher: §10 error table rows for `LLMUnavailable` / `LLMError` (lines 261-262), AC-28 (timeout now raises `LLMUnavailable`), OQ-3 (resolved). Both `changelog.md` files get an entry. |
| Data (schema, statuses, `data/` files) | None. No migration, no new status, no new config key. `architecture/data.md:70` (`failed` meaning) gets "timeouts stop the run too". `data/decisions.jsonl` and `data/resume_profiles.json` unchanged (failed and timed-out calls are not logged, as today). |
| CLI / dashboard | `jobbot decide` and `jobbot scan --decide`: a timeout now ends the run with the stop line instead of `-> failed` lines. Exit code stays as today's abort (0) (OQ-3, decided). Error text of `resumes index`, `match`, `eval` gains the hint. No new command or flag; README/CLAUDE.md Commands unchanged. No dashboard yet. |
| Prompts / decision schema | None. No prompt version bump; `jobbot eval` before/after is not needed (no prompt or matching change), but a run can confirm nothing else moved. |
| Safety rules | None weakened (§2.5). `.claude/rules/llm.md:8` text ("`LLMUnavailable` (Ollama down, OOM, HTTP error) stops the run") must add timeouts. |
| Other capabilities | resume-matcher: client contract changes (AC-28). indeed-scanner: none (the scan itself makes no LLM call; `scan --decide` inherits the decide behaviour). Docs: `CLAUDE.md` decide_pending bullet (line 106) and `architecture/overview.md:67-68` should mention timeouts (the developer is asked before `CLAUDE.md` is edited). |

## 5. Acceptance criteria
"Fake client" means an `OllamaClient` whose HTTP layer is an `httpx.MockTransport` (no real
Ollama, no network). "Fake matcher" means the existing `FakeMatcher` in
`tests/test_db_pipeline.py`. All tests run in the default `pytest` run (not `-m llm`).

- **AC-C1: Timeout is a stop-the-run error.** When the HTTP call to `/api/chat` raises
  `httpx.ReadTimeout`, `httpx.ConnectTimeout`, `httpx.WriteTimeout` or `httpx.PoolTimeout`,
  `OllamaClient.chat_json` raises an exception that is an instance of `LLMUnavailable` (and so of
  `LLMError`). Changes resume-matcher AC-28.
  Verified by: a parametrized unit test (new `tests/test_llm_client.py`) with a fake client.
- **AC-C2: Timeout message.** That exception's message contains the model name from settings,
  the configured `timeout_s` value, and a hint naming both a smaller model (`--model`) and
  `llm.timeout_s`.
  Verified by: the AC-C1 test asserts the substrings, using a non-default model name and
  `timeout_s` so the values are not just defaults.
- **AC-C3: Timeout on a later attempt.** If the first attempt returns invalid JSON and the second
  attempt times out, `chat_json` raises the timeout error of AC-C1 (not "invalid JSON after 2
  attempts"). The same holds when the no-`think` retry after an HTTP 400 "thinking" response
  times out.
  Verified by: unit tests with a fake client whose transport answers in sequence.
- **AC-C4: Invalid JSON is still per-job.** Two invalid answers raise an `LLMError` that is
  **not** an `LLMUnavailable`. A connection error and a non-200 status still raise
  `LLMUnavailable` (rest of AC-28, regression).
  Verified by: unit tests with a fake client.
- **AC-C5: The run stops on the first timeout.** With three decidable jobs `a`, `b`, `c` where
  the matcher decides `a` and raises the client's timeout exception for `b`: `decide_pending`
  calls the matcher exactly for `[a, b]`, returns `decided == 1`, `failed == 0`,
  `stats.aborted` equal to the timeout message, and `on_decision` is not called for `b`.
  Changes job-store AC-11 (now covers timeouts).
  Verified by: unit test in `tests/test_db_pipeline.py` with the fake matcher raising the real
  timeout exception class.
- **AC-C6: No job is touched by the stop.** In the AC-C5 scenario, job `a` keeps its saved
  status, and jobs `b` and `c` stay `new` with `error`, `decision` and `decided_at` NULL
  (`store.counts()` is `{<a's status>: 1, "new": 2}`); both are returned by `to_decide()` in the
  same order next time.
  Verified by: assertions in the AC-C5 test.
- **AC-C7: Per-job failure unchanged.** A matcher `LLMError` that is not `LLMUnavailable` still
  marks only that job `failed` and the run continues (job-store AC-10, narrowed to non-timeout
  errors).
  Verified by: the existing `test_decide_pending_sets_statuses` keeps passing unchanged, plus one
  case using the real "invalid JSON after 2 attempts" exception produced by the AC-C4 fake client.
- **AC-C8: CLI output on a timeout stop.** `jobbot decide` with a fake matcher that decides one job
  and then times out prints the `[1/n] ... -> <status>` line, `Decided 1 (...)`, and a stop line
  starting with `Stopped` that contains the timeout message with the hint. It prints no
  `-> failed` line. The exit code is 0, the same as today's abort exit code (OQ-3, decided
  2026-11-27).
  Verified by: a `typer.testing.CliRunner` test with `cli._build_matcher` monkeypatched to return
  the fake matcher and settings pointing `data_dir` at `tmp_path` (no real Ollama, no real
  `data/jobs.db`).
- **AC-C9: Timeout before any job.** If profiling inside `jobbot decide` (`_build_matcher`) times
  out, the command prints `Error: <timeout message with hint>`, exits 1, and no job row changes.
  Verified by: a `CliRunner` test with `_build_matcher` monkeypatched to raise the timeout
  exception; the test checks `store.counts()` before and after.
- **AC-C10: Other commands keep stopping with `Error:`.** A timeout in `jobbot resumes index`
  prints `Error: <timeout message with hint>` and exits 1 (behaviour as today, message as
  AC-C2; OQ-1, decided 2026-11-27).
  Verified by: a `CliRunner` test with `build_profiles` (or the client) monkeypatched to raise
  the timeout exception. `match` and `eval` use the same `except LLMError` pattern
  (`cli.py:179, 230`) and are covered by inspection in the review.
- **AC-C11: Docs match the code.** The job-store spec (BR-9, BR-10, T-8, T-10, §9, AC-10, AC-11,
  OQ-2), the resume-matcher spec (§10, AC-28, OQ-3), `architecture/data.md:70`,
  `architecture/overview.md:67-68`, `.claude/rules/llm.md:8` and both `changelog.md` files
  describe timeouts as stopping the run. `CLAUDE.md:106` is updated only with the developer's
  OK.
  Verified by: review grep for `timeout`, `timed out`, `LLMUnavailable` across `documentation/`,
  `.claude/rules/` and `CLAUDE.md` (M-001).
- **AC-C12: Suite and lint pass without Ollama.** `.venv\Scripts\python -m pytest` and
  `.venv\Scripts\ruff check src tests` pass with Ollama stopped.
  Verified by: running both commands; the output is pasted in the review.

## 6. Migration and compatibility
- **`data/jobs.db`:** no schema change and no migration. Existing rows are untouched.
  Jobs that already became `failed` through a timeout in earlier runs (error text starting with
  `Ollama timed out after`) stay `failed`; the user re-queues them with
  `jobbot decide --retry-failed`, as today. The change does not rewrite statuses.
- **Cached resume profiles** (`data/resume_profiles.json`): unaffected; cache keys (sha256,
  prompt version, model) do not change.
- **`data/decisions.jsonl`:** unaffected. Timed-out calls were never logged and still are not
  (resume-matcher OQ-7 stays open).
- **Config:** no new key; `llm.timeout_s` keeps its meaning and its default of 600 s (OQ-2,
  decided 2026-11-27).
- **Code that imports `LLMError` / `LLMUnavailable`:** both names stay. A new subclass, if the
  plan adds one, is additive.

## 7. Open questions and assumptions

### Open questions (each with a recommendation)
All four were resolved by the developer in chat on 2026-11-27 by accepting every
recommendation below. None is open any more.

- **OQ-1: Should a timeout in `jobbot resumes index` (profiling) behave the same way?**
  **Decided (developer in chat, 2026-11-27):** yes. `resumes index` keeps stopping on the first
  timeout and shows the same message with the hint (comes from the client change). The lost
  partial profiling progress (resume-matcher OQ-9) stays out of scope. AC-C10 applies as written.
  Today it already stops on the first timeout: `Error: Ollama timed out ...`, exit 1
  (§1.4, `cli.py:78-79`), but without the hint, and profiles finished earlier in that run are
  lost (`profiler.py:108-110`).
  *Recommendation:* yes, keep stopping on the first timeout and show the same message with the
  hint. This comes for free if the classification lives in the client (§2.4). Keep the lost
  partial progress (resume-matcher OQ-9) out of this change; it is a separate Lane C fix.
  Not blocking: the plan can proceed on this recommendation.
- **OQ-2: Should the default `llm.timeout_s` (600 s) change?**
  **Decided (developer in chat, 2026-11-27):** no. Keep `llm.timeout_s` = 600; no config change
  in this change.
  *Recommendation:* keep 600 s in this change. Once a timeout stops the run, a stuck model costs
  one wait instead of one wait per job, so a long default is much less harmful. `gpt-oss:20b`
  runs mostly on CPU here and a first call (model load plus prompt evaluation) can legitimately
  take minutes; a lower default would risk false stops. Revisit after measuring real
  `latency_s` values in `data/decisions.jsonl` (a Lane D tweak to `config.py:30` and
  `settings.example.yaml:9`). Not blocking.
- **OQ-3: Exit code when the run stops.** Today a stop on `LLMUnavailable` exits 0
  (`cli.py:394-397`).
  **Decided (developer in chat, 2026-11-27):** a stopped decide run exits 0, as today, also for
  timeouts. AC-C8 asserts exit code 0.
  *Recommendation:* keep 0 for timeouts too, for consistency; a non-zero
  exit for both causes would be a separate CLI-contract change. Not blocking.
- **OQ-4: A job that always times out.** The stopped job stays `new` and is first in line next
  time (`to_decide` orders by `first_seen_at`, `id`), so a job that times out for its own
  reasons would stop every run at the same place, and there is no CLI way to skip it.
  **Decided (developer in chat, 2026-11-27):** accept the risk for now (R-3). No per-job
  timeout count or skip mechanism in this change.
  *Recommendation:* accept for now. Prompts are bounded (`max_jd_chars`), so this is unlikely,
  and the hint points to the real fixes. Revisit (e.g. a per-job timeout count) only if it is
  seen in practice. Not blocking.

### Assumptions
- **A-1:** The client does the classification (§2.4). Suggested: a new `LLMTimeout(LLMUnavailable)`
  so the stop line can say "timed out" and tests can check the type. The plan makes the final
  choice; either way the pipeline needs no new `except` branch.
- **A-2:** All four httpx timeout subclasses count (a `ConnectTimeout` means Ollama accepted no
  connection in time, which is also a stuck server).
- **A-3:** `jobbot scan --decide` gets the same behaviour, because it calls the same
  `_run_decide` (`cli.py:353-354`).
- **A-4:** Testing the client needs a seam for the HTTP transport, since `OllamaClient` builds its
  own `httpx.Client` (`client.py:38`). The plan picks the seam (for example an optional
  `transport` argument, or replacing `_http` in the test) without changing runtime behaviour.
- **A-5:** No DB, prompt, schema, config-key or Indeed change (§4).

### Risks
- **R-1: Wider meaning of `LLMUnavailable`.** Any code that catches `LLMUnavailable` now also gets
  timeouts. Today that is only `pipeline.py:43`, which is the intended effect (§1.5). New code
  must keep this in mind; the docstring at `client.py:21-23` should be updated.
- **R-2: A one-off slow call now stops a run** that would previously have failed one job and
  continued. With a 600 s budget this needs a really stuck call, and the user can rerun.
- **R-3: Poison job** (OQ-4; risk accepted by the developer on 2026-11-27).
- **R-4: Doc drift (M-001).** Six docs plus `CLAUDE.md` describe timeouts as per-job failures
  (AC-C11 lists them). Missing one would leave the docs wrong.
- **R-5: Untested client (M-002).** `llm/client.py` has no tests today. This change adds the first
  ones (AC-C1..AC-C4); the seam (A-4) must not alter production behaviour.
