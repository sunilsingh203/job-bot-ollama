# Plan approval: indeed-scanner/changes/failure-screenshots

> **Recorded by the AI from the developer's chat approval** (ADR-0005). The AI did not approve
> this plan; the developer did, in chat.

| Field | Value |
|---|---|
| Approver | the developer (repo owner) |
| Date | 2026-11-27 |
| Approved commit hash | `dba1e52` |
| Specification / change definition | [change-definition.md](change-definition.md) (AC-C1..AC-C16) |
| Implementation plan | [implementation-plan.md](implementation-plan.md) (11 steps, including step 7, the guard) |

## Developer's words (chat, 2026-11-27)
> "generate all the plan approvals for me now"

Then the developer answered the approval questions:
- **Approval mode:** "Approve in chat, I record". The option text named this change: *"write
  plan-approval.md for changes 1 and 2"*, where change 2 = `indeed-scanner/changes/failure-screenshots`.
- **Guard (OQ-5):** "Yes, add the guard". Stop the scan after 2 Cloudflare/sign-in timeouts in a row.
- **A-8:** "Yes, stop that search". A human-wait timeout on a results page ends that search's paging.

## Scope approved
The change definition and implementation plan at commit `dba1e52`, as written:
- A PNG and the page HTML are saved to `data/screenshots/` at the 5 failure points, and the path
  is printed.
- Retention is set by `browser.screenshots_keep` (default 50).
- A page-load error stops the scan. Other failures skip the item and carry on.
- A Cloudflare/sign-in timeout skips the item (OQ-4), but 2 in a row stop the scan (OQ-5 guard).
- Taking a screenshot never crashes the scan and never navigates.
- No DB change. 29 new tests.

## Conditions / notes
- Build order: after `job-store/changes/llm-timeout-stops-run` is implemented, and before
  `indeed-scanner/changes/scan-cap-and-paging`.
- Safety: OQ-4 deliberately relaxes the "stop on an unsolved check" behaviour. The guard is the
  agreed mitigation and must be built (step 7 is not optional).
- If the spec or plan changes after `dba1e52`, `/implement-feature` lists the diff and asks again.

## Signature
Approved by: the developer (in chat; recorded by the AI)   Date: 2026-11-27
