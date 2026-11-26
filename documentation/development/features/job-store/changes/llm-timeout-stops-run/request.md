# Request: llm-timeout-stops-run

> Lane B (material change to `job-store` / `decide` behaviour). Drafted by Claude at the
> developer's request on 2026-11-27 from the as-built review. The developer may edit it.
> Next: `/define-feature job-store/changes/llm-timeout-stops-run` → `change-definition.md`.

| | |
|---|---|
| Requested by | the developer |
| Date | 2026-11-27 |
| Related capability | `job-store` (decide pipeline); touches `resume-matcher` (`llm/client.py`) |
| Mistakes log | M-003 |

## What
When Ollama **times out**, `jobbot decide` should stop the whole run, the same way it already
does when Ollama is down. The job should stay `new`. Today it doesn't stop:
- `src/jobbot/llm/client.py:105-106` turns `httpx.TimeoutException` into a plain `LLMError`
  instead of `LLMUnavailable`.
- `src/jobbot/pipeline.py:46` then marks that one job `failed` and moves on to the next job.

## Why
A timeout almost always means the model itself is stuck: it's too slow, ran out of memory, or is
still loading (`gpt-oss:20b` on 6 GB VRAM). It rarely means one particular job is bad. With
`llm.timeout_s = 600`, a stuck model makes every job wait up to 10 minutes and then marks it
`failed`, one after another. A run of 50 jobs can waste hours, and afterwards every job has to be
re-queued with `--retry-failed`.

## Done when
- A timeout during `decide` stops the run with a clear message (model name, timeout value, a hint
  to try a smaller model or a larger `llm.timeout_s`).
- The job being decided stays `new`, and no other job is touched.
- A real per-job problem (invalid JSON after the retry) still marks only that job `failed`.
- Unit tests cover both cases with a fake client. No real Ollama is needed.

## Open questions for /define-feature
1. Should the first timeout stop the run immediately, or should the job be retried once before
   stopping?
2. Should a timeout during `jobbot resumes index` (profiling) also stop with the same message?
   (It already ends with an error there; check this.)
3. Should the default `llm.timeout_s` (600 s) change?

## Notes
- From the as-built review (2026-11-26): resume-matcher OQ-3 and the job-store open questions.

## Decisions (2026-11-27, developer in chat)
- **Open question 1 (retry or stop): stop immediately.** The first Ollama timeout during
  `jobbot decide` stops the run. There is no retry of the job. The job being decided stays
  `new`, and no other job is touched.
- **Message:** the stop message names the model, the timeout value and a hint (try a smaller
  model or a larger `llm.timeout_s`).
- **Per-job invalid JSON is unchanged:** after the existing one retry, it still marks only that
  job `failed`, and the run continues.
- **Not decided yet** (carried into `change-definition.md` as open questions, each with a
  recommendation):
  - Open question 2: whether a timeout during `jobbot resumes index` (profiling) should behave
    the same way.
  - Open question 3: whether the default `llm.timeout_s` (600 s) should change.
