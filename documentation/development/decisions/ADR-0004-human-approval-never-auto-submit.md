# ADR-0004: Human approval for every application; never auto-submit

**Status:** Accepted, 2026-11-26

## Context
jobbot applies to jobs on the developer's behalf, using their real Indeed account and their
personal data. A wrong application (wrong resume, false answer, an unsuitable job) can't be taken
back and reflects on the candidate. The LLM's decisions are good but not perfect (small models
especially), and job descriptions are untrusted text. Automated submission also raises the risk
of Indeed flagging the account.

## Options
1. **Fully automatic**: decide and submit without a human. Fastest; no way to catch mistakes;
   highest account risk.
2. **Approve, then auto-submit**: the user approves in a dashboard and the bot submits. Still
   hides the final filled form from the user, including any LLM-written answers.
3. **Approve before fill, and the user clicks Submit**: the user approves the job and resume in
   the dashboard; the bot fills the form and stops on Indeed's final review page; the user checks
   it and clicks Submit.

## Decision
Option 3.
- The bot never clicks Submit. It stops on the final review page (`ready_to_submit`).
- The bot fills only jobs the user `approved`.
- Answers come from `profile.yaml`. An LLM-written answer is marked **LLM-generated** so the user
  checks it before submitting.
- The bot detects the confirmation page after the user submits and marks the job `applied`.
- An auto-submit path is added only if the developer explicitly asks, behind a config flag that
  defaults to `false`, with a new ADR.

## Consequences
- Throughput is limited by the user's time, which also keeps volume at a human, account-safe pace
  (plus the daily fill cap).
- The review dashboard and the "stop before Submit" behaviour are required parts of the design,
  not extras.
- The form filler must reliably recognise the final review page and the confirmation page, and
  tests must show it never triggers Submit.
- `plan-approval.md` for `form-filler` must state how this rule is kept.
