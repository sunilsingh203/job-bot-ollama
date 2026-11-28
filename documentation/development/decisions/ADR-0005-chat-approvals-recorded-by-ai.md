# ADR-0005: Plan approvals may be given in chat and recorded by the AI

- **Status:** Accepted
- **Date:** 2026-11-27
- **Supersedes:** the "human-only `plan-approval.md`" rule in the original workflow (section 4 and
  the protections list in section 5)

## Context
The workflow required the developer to write every `plan-approval.md` by hand, and the AI was never
allowed to create one. On 2026-11-27 the developer asked the AI to generate the approvals. They
chose to approve in chat and have the AI record the approval, rather than writing the files by hand.

## Options
1. **Keep the human-only rule.** The developer writes every approval file by hand.
2. **The AI prefills, the developer signs.** The AI fills everything except the approver and signature.
3. **Chat approval, recorded by the AI.** The developer explicitly approves a named plan in chat, and the AI writes the file and marks it as recorded.

## Decision
Option 3. The approval still comes **only from the developer**. The file just records it. Rules:
- The developer's chat message must explicitly approve the specific plan(s), by naming them or by
  answering a question that names them. A vague "go ahead" or "looks good" is not enough.
- The AI never approves on its own initiative, and never approves a plan that still has blocking
  open questions (for example values that need a real scan first).
- The recorded file says **"Recorded by the AI from the developer's chat approval"**. It quotes the
  developer's words, and it fills in the date, the approved commit hash (the commit containing
  the spec and plan), the scope, and the conditions the developer gave.
- The AI never edits an existing approval. A changed plan needs a new approval.
- `/implement-feature` accepts either a hand-written approval or a recorded one that carries the
  mark and the quote.

## Consequences
- Approvals are faster. The commit hash still ties each approval to the exact spec and plan text.
- An AI-written file looks the same as a human one, so the mark and the quote are what make it
  auditable. Without them, `/implement-feature` stops.
- The developer can go back to option 1 at any time by superseding this ADR.
