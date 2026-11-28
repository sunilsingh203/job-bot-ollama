# AI-Assisted Development Workflow (jobbot)

> New here? Read the 5-minute [WORKFLOW-GUIDE.md](WORKFLOW-GUIDE.md) first.

This is the spec-driven workflow for **jobbot**. It adapts the generic "Spec-Driven, AI-Assisted
Development Workflow" blueprint to this project: a single-user Python tool with no server, no
web API and no accounts.

It describes **how** we work. It is a strong default, not a cage. The developer can adjust, skip
or override any part of it (see [section 5](#5-flexibility-rules)). When they do, the AI follows
the instruction and keeps the docs consistent.

`CLAUDE.md` at the repo root is the condensed version the agent reads on every session. The focused
rule files live in `.claude/rules/`, and the workflow commands in `.claude/commands/`.

---

## 0. Project parameters

| Parameter | Value |
|---|---|
| PROJECT_NAME | **jobbot** (repo `local-llm-job-automate`) |
| DOMAIN / PURPOSE | A personal, single-user tool. It scans Indeed India, uses a **local LLM** (Ollama, `gpt-oss:20b`) to either skip a job or pick the best resume for it, and pre-fills "Easily apply" forms. A human approves every application and clicks Submit. |
| FRONTEND | Typer CLI (`jobbot`), plus a Streamlit review dashboard (planned) |
| BACKEND | Python 3.13 package `src/jobbot` (no server, no HTTP API) |
| DATABASE | SQLite, `data/jobs.db` |
| REPO STYLE | Single repo, one package |
| AUTH | **None.** Local, single-user tool: no server, no accounts, no sessions. Security is about keeping data local, never auto-submitting, never scripting the Indeed login or bypassing CAPTCHAs, keeping personal data out of Git, and treating LLM output and scraped HTML as untrusted input. See [section 11](#11-security-baseline-adapted). |
| PLAN APPROVER | The developer (the repo owner), called "the approver" in these docs |
| GOVERNANCE LEVEL | **standard** (see [section 7](#7-governance-levels)) |

---

## 1. Repository layout

The project keeps its existing `src/` layout (see [ADR-0002](decisions/ADR-0002-keep-src-layout.md)).
The blueprint's `apps/web`, `apps/api` and `apps/db` map onto it like this:

| Blueprint | jobbot |
|---|---|
| `apps/web/` (frontend) | `src/jobbot/cli.py` (Typer CLI) and `src/jobbot/dashboard/` (Streamlit, planned) |
| `apps/api/` (backend) | `src/jobbot/` modules: `matcher/`, `llm/`, `resumes/`, `platforms/`, `pipeline.py`, `db.py` |
| `apps/db/` (schema) | `src/jobbot/migrations/NNNN_name.sql`, the only record of schema changes ([ADR-0003](decisions/ADR-0003-sql-migration-files.md)) |

```
local-llm-job-automate/
├── CLAUDE.md                     # condensed agent rules (always loaded)
├── .claude/
│   ├── rules/                    # safety, database, llm, indeed, docs
│   ├── commands/                 # workflow slash commands (section 6)
│   └── mistakes/
│       └── common-mistakes.md    # Claude's recurring mistakes + how to avoid them (section 14)
├── config/                       # settings.example.yaml, searches.yaml, mnc_companies.txt
├── profile.example.yaml          # template; profile.yaml is gitignored
├── resumes/                      # gitignored except resumes.example.yaml
├── data/                         # gitignored: jobs.db, resume_profiles.json, decisions.jsonl, screenshots/
├── browser_profile/              # gitignored: the bot's Chrome profile
├── src/jobbot/
│   ├── migrations/               # NNNN_name.sql, applied by JobStore via PRAGMA user_version
│   └── ...                       # see architecture/overview.md
├── tests/                        # pytest; fixtures in tests/fixtures/
└── documentation/
    ├── customer/                 # the developer's goals, platform notes, Indeed observations
    └── development/
        ├── AI-DEVELOPMENT-WORKFLOW.md   # this file
        ├── architecture/         # overview, security, data
        ├── features/             # one folder per capability (specs, plans, approvals, reviews)
        ├── decisions/            # ADRs
        ├── standards/            # coding, git, testing, documentation
        ├── changes/              # Lane C small changes, one folder each
        └── templates/            # starting points for every artifact
```

---

## 2. Core principle: vertical, feature-oriented development

Each feature is built through every layer it touches, together:

```
Requirement -> DB impact (migration) -> core logic (matcher / pipeline / platform / llm)
            -> interface (CLI command, dashboard screen) -> tests -> docs
```

There is no HTTP API. The "API" of a capability is its Python interface (the functions and
classes other modules call) and its CLI commands. A feature is done only when it works across
every layer it affects.

---

## 3. Classify every piece of work first

| Lane | What it is | Where the artifacts go |
|---|---|---|
| A. New capability | A new feature or module (e.g. `review-dashboard`, `form-filler`) | `documentation/development/features/<capability>/` |
| B. Material change | A significant change to an existing capability | `documentation/development/features/<capability>/changes/<change>/` |
| C. Small change / fix | Bug fix, minor behaviour change, small CLI tweak | `documentation/development/changes/<change>/` |
| D. Developer-directed tweak | A trivial edit the developer asks for in chat | A line in the feature's `changelog.md` (or nothing, if purely cosmetic) |

**Escalation rule.** If work called "small" or "quick" affects any of the following, say so and
recommend moving it up to Lane B. The developer makes the final call.

- business behaviour (what gets skipped, applied to or filled)
- persisted data meaning (DB schema, job statuses, the `data/` file formats)
- CLI contracts (command names, flags, exit behaviour other scripts rely on)
- the approval workflow (approve-before-submit, the human Submit step)
- the safety rules in `CLAUDE.md` (local-only, no auto-submit, account protection, no invented facts)
- architecture or shared code (`models.py`, `db.py`, `config.py`, `llm/client.py`)
- external integrations (Indeed pages and selectors, the Ollama API)
- prompts or the decision schema (they change decision accuracy; see [standards/testing.md](standards/testing.md))
- the migration strategy

---

## 4. Lifecycle and artifacts

All templates live in [`templates/`](templates/).

### Lane A: new capability

0. **Branch** -> before the first file, create `feature/<capability>` from the **latest `develop`**
   (`git fetch`, `git switch develop`, `git pull --ff-only`, `git switch -c feature/<capability>`).
   Everything below happens on that branch and goes into `develop` as one PR
   ([standards/git.md](standards/git.md), [ADR-0006](decisions/ADR-0006-develop-and-feature-branches.md)).
0b. **Describe** -> `README.md`, **written by the developer** in short, plain English (template
   `templates/feature-readme.md`): what they want, why, must have / nice to have / not now, and
   done when. `/define-feature` stops and asks for it if it's missing. The AI may draft it from the
   developer's chat description, marked as drafted, but only with the developer's OK.
1. **Define** -> `specification.md`: purpose, actors, scope / out of scope, business rules,
   data entities, states and transitions, permissions and data scope (for jobbot: what the
   bot may do on its own vs. what needs the human), validation and error cases, numbered
   acceptance criteria (AC-1, AC-2, ...), open questions and assumptions, dependencies.
2. **Plan** -> `implementation-plan.md`: affected layers (DB / core / CLI / dashboard /
   security / tests / docs), **explicit DB changes with migration file names**, module
   interfaces and CLI commands, dashboard screens, a test plan mapped to the ACs, ordered
   steps, risks, open questions and the ADRs needed.
3. **Approve** -> `plan-approval.md`: approver, date, the Git commit hash at which the spec and
   plan were approved, the scope approved, conditions. Either the developer writes it by hand, or
   the developer **explicitly approves that specific plan in chat** and the AI records it, marked
   "Recorded by the AI from the developer's chat approval" with the developer's words quoted
   ([ADR-0005](decisions/ADR-0005-chat-approvals-recorded-by-ai.md)). **The AI never approves on
   its own, from a vague go-ahead that doesn't name the plan, or while blocking questions are
   open, and never fakes an approval.**
4. **Implement**: only when `plan-approval.md` exists. Under standard governance, if the spec or
   plan changed after the approved commit, or implementation shows they must change, the AI stops
   that part, updates the docs and tells the developer before continuing.
5. **Review** -> `review.md`: every AC checked, findings ranked by severity with file/line
   references, plus safety, data handling, tests and doc consistency.
6. **Remediate**: fix the findings and record each as resolved, deferred or rejected, with the reason.

### Lane B: material change

Branch: `change/<capability>-<change>` from the latest `develop` (step 0 of Lane A). The developer
first writes the change's `README.md` (step 0b of Lane A). Older Lane B folders use `request.md` for this.

Same as Lane A, inside `features/<capability>/changes/<change>/`:
`change-definition.md` -> `implementation-plan.md` -> `plan-approval.md` (developer, by hand or recorded from chat) -> implement -> `review.md`.

### Lane C: small change / fix

Branch first: `fix/<change>` from the latest `develop`, before `implementation-plan.md` is written.

In `documentation/development/changes/<change>/` (see [changes/README.md](changes/README.md)):
`request.md` (**written by the developer**, can be short; `/plan-small-change` stops if it's
missing) -> `implementation-plan.md` (the AI) -> the developer's
go-ahead in chat or a line in the file -> implement -> `review.md` (brief verification).

### Lane D: developer-directed tweak

The developer asks in chat ("rename this flag", "change the default delay"). The AI does it, then:
- lists the files that changed
- updates the spec or adds a line to the feature's `changelog.md` if documented behaviour changed
- stops and suggests Lane C or B if it turns out bigger than it looked

---

## 5. Flexibility rules

- The developer can **edit any spec or plan at any time**, by hand or through chat. The AI then
  updates the related artifacts and flags anything that now conflicts (e.g. an AC vs. new behaviour).
- **Chat instructions** can refine or override the spec. The AI records the decision in the
  relevant document, so the repo (not the chat) is the lasting record.
- The developer can **skip steps** (e.g. no formal review for an experiment). The AI does so but
  states once what was skipped.
- If a chat instruction **contradicts** the spec, the AI points out the conflict in one line,
  proposes a resolution and follows the developer's choice.
- Templates are starting points. Sections can be added, removed or renamed per feature.
- These protections **stay in place unless the developer explicitly removes them**:
  - `plan-approval.md` needs the developer's explicit approval (by hand, or recorded from an
    explicit chat approval of that plan; ADR-0005)
  - explicit SQL migration files
  - no secrets or personal data in Git
  - the `CLAUDE.md` safety rules: never auto-submit, local-only LLM and data, no scripted login,
    no CAPTCHA bypass, never invent facts on a form. (These replace the blueprint's
    "backend-enforced authorization", which has no meaning for a single-user local tool.)

---

## 6. Workflow commands

Implemented as Claude Code slash commands in `.claude/commands/`.

| Command | Does |
|---|---|
| `/define-feature <capability>` | Reads the customer notes, architecture and code, asks questions, drafts `specification.md` (or `change-definition.md` for `<capability>/changes/<change>`) |
| `/plan-feature <capability>` | Reads the spec and the existing code, drafts `implementation-plan.md` |
| `/implement-feature <capability>` | Checks the approval gate, then implements the plan step by step |
| `/review-feature <capability>` | Reviews the result against the spec and every AC, writes `review.md` |
| `/remediate-review <capability>` | Fixes review findings, records how each was resolved |
| `/plan-small-change <change>` | Reads `changes/<change>/request.md`, writes the plan |
| `/implement-small-change <change>` | Implements after the developer's go-ahead |
| `/review-small-change <change>` | Verifies the change against the request, writes `review.md` |

For a Lane B change, pass `<capability>/changes/<change>` to the feature commands.

Every command reads the relevant docs first, inspects the existing code, states its assumptions,
and ends with a short report: what changed, where, and what's next.

---

## 7. Governance levels

| Level | Rule |
|---|---|
| strict | Approval file **and** a commit-hash match are required before any feature implementation. Chat requests for Lanes A/B are refused until approved. |
| **standard (selected)** | Lanes A/B need a `plan-approval.md` (written by the developer, or recorded by the AI from the developer's explicit chat approval) before implementation. Lanes C/D go ahead on the developer's chat go-ahead. The AI records decisions in the docs. |
| light | Spec and plan are optional. The AI updates docs after the fact. |

The developer can switch levels for the whole project or for one feature. Record a switch in
this section (project-wide) or in the feature's `specification.md` (per feature).

---

## 8. Mandatory working rules (all lanes)

1. Understand the request, then read the relevant feature and architecture docs. For Lanes A/B/C,
   work on that work's own branch, cut from the latest `develop` (never directly on `develop` or `main`).
2. Inspect the existing implementation before proposing anything.
3. Identify the affected layers: DB, core logic, CLI/dashboard, safety rules, tests, docs.
4. List ambiguities, conflicts and missing decisions, and **ask. Don't invent business rules.**
5. Give a short plan before making substantial changes.
6. Implement, then run the tests and lint (`.venv\Scripts\python -m pytest`,
   `.venv\Scripts\ruff check src tests`). Run `jobbot eval` when prompts or matching changed.
7. Review your own diff. Check it against the acceptance criteria.
8. Update the docs when behaviour or architecture changed.
9. **Never claim a test or command passed unless you actually ran it.**
10. Check your work against the relevant entries in the common-mistakes log (section 14), and
    update the log before you finish.

When presenting a plan, always state: what you understood · what will change · DB impact ·
core/interface impact (modules, CLI, dashboard) · safety impact · testing approach ·
open questions and assumptions.

---

## 9. Database authority

- The AI may inspect the schema, propose tables/columns/indexes/constraints and write SQL.
- Every schema change is an explicit migration file at
  **`src/jobbot/migrations/NNNN_name.sql`** (e.g. `0002_add_fill_columns.sql`). The files ship
  inside the package. `JobStore` applies, in order, every file whose number is higher than the
  database's `PRAGMA user_version`, then sets `user_version` to that number.
- Application code is never the only record of the schema: no `CREATE TABLE` / `ALTER TABLE`
  inside Python code ([ADR-0003](decisions/ADR-0003-sql-migration-files.md)).
- A migration file is never edited after it has been applied to the developer's `data/jobs.db`.
  Fix it with a new migration.
- Destructive or hard-to-reverse changes (dropping tables or columns, rewriting status values,
  bulk deletes) need explicit approval from the developer before they run. Suggest backing up
  `data/jobs.db` first.
- **N/A:** "connect with a least-privilege DB user". SQLite is a local file with no users or
  roles. The equivalent protection is file location: the DB lives in the gitignored `data/` folder.

---

## 10. Architecture discipline

- Prefer consistency with the existing code over novelty.
- Don't add frameworks, libraries, patterns or cross-cutting abstractions on your own
  initiative. Propose them separately, with a reason. New dependencies go in `pyproject.toml`.
- Platform code stays under `platforms/<name>/`. It must not leak into `matcher/` or `llm/`.
- Record significant decisions as ADRs in [`decisions/`](decisions/README.md).
- Stay in scope: no unrelated refactors, renames or speculative features. Report nearby
  technical debt separately.

---

## 11. Security baseline (adapted)

jobbot has no server, no network listener of its own (the planned Streamlit dashboard binds to
localhost), no accounts and one user. The full threat model is in
[architecture/security.md](architecture/security.md). Mapping of the blueprint's items:

| Blueprint item | jobbot |
|---|---|
| Treat all client/external input as untrusted, validate on the backend | **Applies.** Scraped Indeed HTML/JSON, job descriptions and LLM output are untrusted. LLM output is validated against a JSON schema and pydantic. SQL always uses parameters. Job description text is data in a prompt, never instructions. |
| Authorization enforced on the backend | **N/A**: single user, no server. The equivalent: actions with outside effects (submitting an application) are never automated. |
| user -> role -> permission model | **N/A**: no users or roles. |
| Data scope on reads/lists/exports | **N/A** as tenancy. Applies as "data stays on this machine": no cloud APIs, analytics or telemetry. |
| Actor identity from the session | **N/A**: no sessions. Approval in the dashboard is by the one local user. |
| Maker-checker / approval flows | **Applies, adapted.** The bot proposes (decide, fill). The human approves in the dashboard and clicks Submit. Status changes live in `db.py` (`JobStore`); the planned review and fill transitions must be checked there too, not only in the UI. Decisions are logged to `decisions.jsonl`, with timestamps in `jobs`. |
| Server-side sessions, HttpOnly cookies, CSRF, CORS | **N/A**: no web server or sessions of our own. The Indeed session lives in `browser_profile/`, which is gitignored and never read or copied by code. |
| Never commit secrets; never log passwords/tokens | **Applies.** Never commit `resumes/`, `profile.yaml`, `config/settings.yaml`, `data/`, `browser_profile/`. Never script the Indeed login or store passwords. |
| Safe error model, no internals exposed | **Mostly N/A** (no API). CLI errors should be clear; stack traces are fine locally but must not dump personal data. |
| Stop and ask when security info is missing | **Applies.** If a change touches any safety rule, stop and ask. |

---

## 12. Testing and completion standard

Write or update tests for normal behaviour, validation failures (bad config, bad LLM JSON),
state-transition rules, important edge cases and regressions. Parsing tests use saved fixtures,
never the live site. LLM-dependent tests are marked `@pytest.mark.llm` and skipped by default.
Details: [standards/testing.md](standards/testing.md).

Work is complete only when:
- the behaviour works across every affected layer
- DB changes are explicit migration files
- input validation is in place and the safety rules still hold
- tests were added, **actually run**, and pass (and `jobbot eval` was run if matching changed)
- the docs match the implementation
- no unrelated changes slipped in

---

## 13. Capabilities

| Capability | Status | Spec |
|---|---|---|
| `resume-matcher` | Built (step 1) | `features/resume-matcher/` |
| `indeed-scanner` | Built (step 2) | `features/indeed-scanner/` |
| `job-store` | Built (step 2) | `features/job-store/` |
| `review-dashboard` | Planned (step 3) | none yet: start with `/define-feature review-dashboard` |
| `form-filler` | Planned (step 4) | none yet: start with `/define-feature form-filler` |

---

## 14. Common-mistakes log

`.claude/mistakes/common-mistakes.md` lists the mistakes Claude has made on this project and how to
avoid each one. `CLAUDE.md` imports it, so every session starts with it loaded. The file's header
holds the full rules. In short:

| Event | Action |
|---|---|
| The developer corrects Claude, a review finds a defect Claude introduced, or Claude catches its own mistake | Add an entry `M-NNN`: **Mistake**, **Why it matters**, **How to avoid**, **Evidence**, **Seen**, **Clean streak** |
| The same mistake happens again | Add 1 to `Seen` and reset `Clean streak` to 0 (no duplicate entry) |
| A task where the entry's situation came up and Claude avoided the mistake | Add 1 to `Clean streak` |
| `Clean streak` reaches 3/3, **or** a test/lint rule/hook now catches it | Delete the entry (git history keeps it) and say so in the task report |

**Why every entry has "How to avoid":** a mistake and its explanation say what went wrong, but
only a concrete rule or check changes what Claude does next time. That line is what Claude checks
its work against before finishing a task.

Where the log is used:

- **Implement commands:** check the relevant entries before reporting. The report lists entries
  applied (streak +1) and any new entries.
- **Review commands:** every defect Claude introduced that could happen again becomes a new
  entry, or bumps the count of an existing one.
- **Remediate:** when a fix adds an automated guard for an entry (a test, a lint rule), delete that entry.

The developer may edit or delete any entry at any time. Claude deletes entries only under the
rules above. Keep it to about 15 short entries.
