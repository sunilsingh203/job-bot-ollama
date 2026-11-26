# How to develop in jobbot: the short guide

A 5-minute read. The full rules are in [AI-DEVELOPMENT-WORKFLOW.md](AI-DEVELOPMENT-WORKFLOW.md);
this page tells you how to use them.

## The idea in one paragraph

We write down **what** we want before we write code. For anything important, Claude first
writes a **spec** (what the feature must do), then a **plan** (how it will be built). **You** read
both and approve them by writing one small file. Only then does Claude write the code, run the
tests and review its own work against the spec. The docs stay in the repo, so anyone (or any new
Claude session) can see why the code is the way it is.

```
 idea ──▶ spec ──▶ plan ──▶ YOU APPROVE ──▶ code + tests ──▶ review ──▶ fix findings ──▶ done
         (Claude)  (Claude)  (you, by hand)    (Claude)        (Claude)    (Claude)
```

## Step 1: Pick a lane

Every piece of work goes in one of four lanes. The bigger the risk, the more paperwork.

| Lane | When | Example in this project | Approval |
|---|---|---|---|
| **A. New feature** | Something the tool can't do yet | The review dashboard, the form filler | You write `plan-approval.md` |
| **B. Big change** | Changes how an existing feature behaves | New status values, a new decide prompt, schema changes | You write `plan-approval.md` |
| **C. Small fix** | A bug or minor tweak | Fix salary parsing, add a `--since` flag | "go ahead" in chat |
| **D. Tiny tweak** | Trivial, just ask | Rename a label, change a log message | none, just ask |

**Not sure?** Ask Claude. If a "small" fix touches the DB schema, a prompt, a safety rule or the
Indeed/Ollama behaviour, Claude will tell you to move it up to Lane B. You decide.

## Step 2: Follow the lane

### Lane A: new feature (example: `review-dashboard`)

| # | You type | What happens | File created |
|---|---|---|---|
| 1 | `/define-feature review-dashboard` | Claude reads the docs and code, **asks you questions**, then writes the spec with numbered acceptance criteria (AC-1, AC-2…) | `features/review-dashboard/specification.md` |
| 2 | `/plan-feature review-dashboard` | Claude writes the plan: DB changes, modules, tests per AC, steps, risks | `implementation-plan.md` |
| 3 | *(you)* read both, edit them or ask Claude to change them, then commit | | |
| 4 | *(you)* copy `templates/plan-approval.md` into the feature folder and fill it in | Claude **can never** write this file | `plan-approval.md` |
| 5 | `/implement-feature review-dashboard` | Claude checks your approval exists, builds step by step, runs pytest + ruff | code, tests, migrations |
| 6 | `/review-feature review-dashboard` | Claude checks every AC (pass/fail), lists findings by severity | `review.md` |
| 7 | `/remediate-review review-dashboard` | Claude fixes findings and records each as resolved, deferred or rejected | `review.md` updated |

Filling in `plan-approval.md` takes about 30 seconds:

```
| Approver             | <your name>                              |
| Date                 | 2026-11-27                               |
| Approved commit hash | a1b2c3d   ← run: git rev-parse --short HEAD |
```

### Lane B: big change to an existing feature

The same 7 steps, using the path `<feature>/changes/<change>`:

```
/define-feature job-store/changes/add-approved-status   → change-definition.md
/plan-feature   job-store/changes/add-approved-status   → implementation-plan.md
(you write plan-approval.md in that folder)
/implement-feature job-store/changes/add-approved-status
/review-feature    job-store/changes/add-approved-status
```

### Lane C: small fix

1. Create `documentation/development/changes/2026-11-27-fix-salary/request.md` (copy the
   template). Write a few lines: **what**, **why**, **done when**.
2. `/plan-small-change 2026-11-27-fix-salary`. Claude writes a short plan.
3. Reply "go ahead" in chat.
4. `/implement-small-change 2026-11-27-fix-salary`, then `/review-small-change 2026-11-27-fix-salary`.

### Lane D: tiny tweak

Just ask in chat: *"change the jobs table to sort by score"*. Claude does it and tells you which
files changed. If it turns out bigger than it looked, Claude stops and suggests Lane C.

## Where things live

```
CLAUDE.md                          rules Claude reads every session
.claude/
  commands/                        the /slash commands above
  rules/                           short rule files (safety, database, llm, indeed, docs)
  mistakes/common-mistakes.md      Claude's past mistakes + how to avoid them
documentation/development/
  WORKFLOW-GUIDE.md                this page
  AI-DEVELOPMENT-WORKFLOW.md       the full rulebook
  features/<feature>/              spec, plan, approval, review, changelog (one folder per feature)
  changes/<date-slug>/             Lane C small fixes
  architecture/                    how the system works (overview, security, data)
  decisions/                       ADRs: big choices and why we made them
  standards/                       coding, git, testing, documentation
  templates/                       copy these when starting a new doc
src/jobbot/                        the code
src/jobbot/migrations/             NNNN_name.sql, the only place the DB schema changes
tests/                             pytest
```

## Rules that never bend

1. **Never auto-submit.** The bot stops on Indeed's final page and you click Submit.
2. **Everything stays local:** only the local Ollama LLM, no cloud APIs.
3. **Protect the Indeed account:** visible Chrome, human-like delays, daily caps. A human solves CAPTCHAs.
4. **Personal data is never committed:** `resumes/`, `profile.yaml`, `data/`, `browser_profile/`, `config/settings.yaml`.
5. **Only a human writes `plan-approval.md`.**
6. **DB schema changes only through a new SQL file** in `src/jobbot/migrations/`. Never edit an old one.
7. **No "tests passed" without actually running them.**

## Claude's mistakes log

`.claude/mistakes/common-mistakes.md` lists the mistakes Claude has made here, each with a
**How to avoid** rule. Claude checks its work against the log before finishing a task.

- Each mistake has an entry: what went wrong, why it matters, how to avoid it, and a **clean streak**.
- If Claude makes the same mistake again, the entry's count goes up and its streak resets to 0.
- After 3 clean tasks in a row, or once a test catches the mistake automatically, the entry is deleted.

You can add or delete entries yourself.

## You can always bend the process

- **Edit any spec or plan** by hand or in chat. Claude keeps the other docs consistent.
- **Skip a step** (e.g. no review for a quick experiment). Claude says once what was skipped.
- **Override in chat.** If that contradicts the spec, Claude points it out in one line and
  follows your choice, then records it in the docs.

## Everyday commands

```powershell
.venv\Scripts\python -m pytest              # unit tests (no LLM)
.venv\Scripts\ruff check src tests          # lint
.venv\Scripts\ruff format src tests         # format
jobbot eval -v                              # matcher accuracy on sample job descriptions
```

Git: one branch per piece of work (`feature/review-dashboard`, `fix/<change>`). Claude commits
only when you ask. More detail is in [standards/git.md](standards/git.md).

## Where we are now

| Feature | Status |
|---|---|
| `resume-matcher`, `indeed-scanner`, `job-store` | Built. Specs written, **waiting for your `plan-approval.md`** |
| `review-dashboard` | Next. Start with `/define-feature review-dashboard` |
| `form-filler` | Later |
