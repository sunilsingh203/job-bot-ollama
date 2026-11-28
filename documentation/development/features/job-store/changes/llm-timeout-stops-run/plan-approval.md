# Plan approval: job-store/changes/llm-timeout-stops-run

> **Recorded by the AI from the developer's chat approval** (ADR-0005). The AI did not approve
> this plan; the developer did, in chat.

| Field | Value |
|---|---|
| Approver | the developer (repo owner) |
| Date | 2026-11-27 |
| Approved commit hash | `dba1e52` |
| Specification / change definition | [change-definition.md](change-definition.md) (AC-C1..AC-C12) |
| Implementation plan | [implementation-plan.md](implementation-plan.md) (11 steps) |

## Developer's words (chat, 2026-11-27)
> "generate all the plan approvals for me now"

Then, asked how approvals should work, the developer chose: **"Approve in chat, I record"**. The
option text named this change: *"write plan-approval.md for changes 1 and 2"*, where change 1 =
`job-store/changes/llm-timeout-stops-run`.

## Scope approved
The change definition and implementation plan at commit `dba1e52`, as written:
- An Ollama timeout raises `LLMTimeout(LLMUnavailable)`, so `jobbot decide` stops on the first
  timeout and the job stays `new`.
- The stop message names the model and timeout, with a hint.
- Invalid JSON is still a per-job `failed`.
- No DB or config change. 15 new tests.

## Conditions / notes
- Step 10 (editing the timeout line in `CLAUDE.md`) still needs the developer's OK at
  implementation time, as the plan says.
- Build order: first, before the two indeed-scanner changes.
- If the spec or plan changes after `dba1e52`, `/implement-feature` lists the diff and asks again.

## Signature
Approved by: the developer (in chat; recorded by the AI)   Date: 2026-11-27
