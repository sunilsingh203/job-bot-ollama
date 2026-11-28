# Local LLM Job Auto-Apply

A personal tool that finds jobs on Indeed, uses a **local LLM** to read each job description and either **pick the best-matching resume** from a resume library or **skip** the job, then pre-fills the application. **A human approves every application before submit.**

> Status: **Step 1 (matcher) and Step 2 (Indeed scanner + SQLite job store + `decide` over the DB) are built.** Steps 3–4 (review dashboard, form filler) are *(planned)*. Update this file as pieces get built.

---

## Non-negotiable rules

1. **Never auto-submit.** The bot fills forms and stops on Indeed's final review page. The user clicks Submit. Don't add an auto-submit path unless the user explicitly asks for one, and keep it behind a config flag defaulting to `false`.
2. **Everything stays local.** Resumes, profile data, job data and LLM calls never leave the machine. Use only the local Ollama server; no cloud LLM APIs, analytics or telemetry.
3. **Protect the user's Indeed account.**
   - Use a visible (non-headless) real Chrome with a dedicated persistent profile. The user logs in by hand once; never script the login or store passwords.
   - Use random human-like delays, and keep a daily cap on fills (default ~25, configurable).
   - Never try to bypass CAPTCHAs or Cloudflare challenges. Pause and ask the user to solve them.
4. **Personal data is gitignored:** `resumes/`, `profile.yaml`, `data/` (SQLite, logs, screenshots) and `browser_profile/`. Commit only `*.example.yaml` templates.
5. **Never invent facts on a form.** Answers come from `profile.yaml`. If the LLM writes an answer to an unknown question, mark it as **LLM-generated** so the user checks it at the Submit step.

---

## Development workflow (spec-driven, governance: **standard**)

Short guide for humans: `documentation/development/WORKFLOW-GUIDE.md`. Full workflow: `documentation/development/AI-DEVELOPMENT-WORKFLOW.md`. Focused rules: `.claude/rules/`. Slash commands: `.claude/commands/` (`/define-feature`, `/plan-feature`, `/implement-feature`, `/review-feature`, `/remediate-review`, `/plan-small-change`, `/implement-small-change`, `/review-small-change`).

1. **Classify work first.** A: new capability → `documentation/development/features/<capability>/`. B: material change → `features/<capability>/changes/<change>/`. C: small fix → `documentation/development/changes/<change>/`. D: trivial chat tweak → just do it, add a `changelog.md` line if documented behaviour changed. If "small" work touches business behaviour, persisted data meaning, the DB schema, safety rules (auto-submit, Indeed account protection, local-only data), the LLM decision contract or prompts, say so and recommend Lane B.
2. **Lanes A/B:** `specification.md` (numbered ACs) → `implementation-plan.md` → **`plan-approval.md`** → implement → `review.md` → remediate. The approval is written by the developer, **or recorded by the AI only when the developer explicitly approves that specific plan in chat** (ADR-0005): mark it "Recorded by the AI from the developer's chat approval", quote their words, add the date and the approved commit hash. **Never approve on your own, from a vague go-ahead, or with blocking open questions. Never fake one.** No implementation for A/B without it.
3. **Lanes C/D** proceed on the developer's go-ahead in chat.
4. **Schema changes only via SQL migration files** in `src/jobbot/migrations/NNNN_name.sql` (applied by `JobStore` via `PRAGMA user_version`). No DDL in Python code. Never edit a migration that has already been applied; add a new numbered file instead. Destructive changes (drops, data rewrites) need explicit approval.
5. Before coding: read the feature's spec/plan and the existing code, list ambiguities and **ask rather than invent rules**. Then plan briefly, implement, run `pytest` + `ruff`, check against the ACs, and update docs. **Never claim a command passed without running it.**
6. Chat instructions may refine or override a spec: point out any conflict in one line, follow the developer's choice, and record it in the docs (the repo is the lasting record, not the chat).
7. Stay in scope. No new frameworks or libraries without proposing them first. Record significant decisions as ADRs in `documentation/development/decisions/`.
8. **Common-mistakes log** (`.claude/mistakes/common-mistakes.md`, loaded below). Before finishing a task, check your work against every relevant "How to avoid" line. Add an entry when the developer corrects you or a review finds a defect you introduced. If the same mistake happens again, add 1 to its count and reset its streak. Add 1 to the streak when you avoided a mistake whose situation came up. Delete an entry at a streak of 3/3 or when a test/lint/hook now guards against it. Report all changes to the log at the end of the task.

@.claude/mistakes/common-mistakes.md

Capabilities: `resume-matcher`, `indeed-scanner` and `job-store` are built (as-built specs are awaiting the developer's review). `review-dashboard` and `form-filler` are planned (no spec yet).

---

## Decisions so far

| Topic | Decision |
|---|---|
| First platform | **Indeed India** (`in.indeed.com`). Other platforms (Wellfound, Greenhouse/Lever) come later. |
| Apply mode | Approve-before-submit (dashboard approval, then the user clicks the final Submit) |
| Job types handled | **"Easily apply"** (Indeed Apply) only. "Apply on company site" jobs go to a *manual* list with the chosen resume and link. |
| Targets | Anywhere in India (onsite/hybrid/remote) + remote jobs outside India |
| Resume axes | **Role track** × **company type** (see below) |
| Cover letters / free text | Generate only when the field is **required** |
| LLM | `gpt-oss:20b` via Ollama (already pulled). Keep the model name in config so a smaller model can replace it. |

### Resume library

Resumes differ by **role track** and **company type**:

| | startup | mnc |
|---|---|---|
| `sde` | sde_startup | sde_mnc |
| `java` | java_startup | java_mnc |
| `devops` (cloud/devops) | devops_startup | devops_mnc |

- `resumes/resumes.yaml` defines the `role_tracks` (id → description shown to the LLM) and lists every file with `roles` (a list: one resume can serve several tracks), `company_type` (`startup|mnc|any`) and optional `notes`. Adding a resume must never require a code change.
- **Current library:** only 2 resumes exist so far: `software_dev` (tracks `sde` and `java`, company type `any`) and `devops_cloud` (track `devops`, `any`). The startup/MNC variants come later.
- The user has **~0.8 years of experience** (entry level), so the rule filters (experience tolerance, senior-title keywords) do a lot of the rejecting.
- **Role track** is decided by the LLM from the job description.
- **Company type** is decided in this order:
  1. the user-maintained MNC list (`config/mnc_companies.txt`)
  2. company size from Indeed's company page (≥ 1,000 employees means MNC; the threshold is configurable)
  3. LLM guess from the job description, as a last resort

---

## Pipeline

```
SCAN ──▶ FILTER ──▶ DECIDE (LLM) ──▶ REVIEW (user) ──▶ FILL (bot) ──▶ SUBMIT (user)
```

1. **Scan:** run saved Indeed searches (keyword × location) and store jobs in SQLite, deduplicated by Indeed job key.
2. **Filter:** cheap rule-based rejects *before* any LLM call: required experience far above the user's, blacklisted companies/keywords, already applied, wrong location.
3. **Decide:** the LLM gets the job description and the **cached structured summaries** of the resumes (not the full resume text), and returns JSON that is checked against a schema:
   ```json
   {"decision": "apply|skip", "role_track": "sde|java|devops|none",
    "company_type": "startup|mnc|unknown", "resume_id": "java_mnc",
    "score": 0-100, "reason": "short explanation"}
   ```
4. **Review:** a dashboard queue where the user approves, rejects or changes the resume.
5. **Fill:** Playwright opens approved jobs, uploads the resume, answers screening questions from `profile.yaml` (LLM fallback, flagged) and **stops before Submit**.
6. **Submit:** the user clicks Submit; the bot detects the confirmation page and marks the job `applied`.

Job status lifecycle (`src/jobbot/db.py`):
- After scan and decide: `new` → `filtered_out` | `skipped` | `pending_review` (apply + Easily apply) | `manual` (apply, but external apply) | `duplicate` | `failed`
- Later steps: `pending_review` → `approved` | `rejected` → `filling` → `ready_to_submit` → `applied`

### Indeed scanning (step 2): how it works and what was learned
- **Scan and decide are separate commands** (`jobbot scan`, then `jobbot decide`, or `scan --decide`). The browser shouldn't sit open while a slow local LLM thinks, and jobs can be scanned even when the LLM can't load.
- **Search results are parsed from embedded JSON:** `window.mosaic.providerData["mosaic-provider-jobcards"]` → `metaData.mosaicProviderJobCardsModel.results[]`. It holds `jobkey`, `displayTitle`, `company`, `formattedLocation`, `indeedApplyEnabled` (= "Easily apply"), `remoteLocation`, `salarySnippet.text`, `pubDate` (ms), `snippet`, plus `loggedIn` on the model. If that JSON is missing, a DOM fallback (`a[data-jk]` cards) is used. All Indeed selectors and markers live in `platforms/indeed/parse.py`.
- **The full description is not in the results JSON.** It's read by clicking the card and reading the right-hand pane (`#jobDescriptionText`), the way a person would.
- **Observed 2026-11-21:**
  - `/viewjob?jk=…` redirects **logged-out** users to sign-in.
  - After a few automated page loads, Cloudflare showed "Additional Verification Required / Verify you are human".
  - The scanner detects both (`is_challenge`, `is_signin`) and **waits for the user** in the visible window (`browser.wait_for_human`, timeout `browser.human_wait_timeout_s`). Never automate past these. If the wait times out, that page or job is skipped (developer decision 2026-11-27). A closed window, or 2 unsolved checks in a row, stop the scan.
- `jobbot login` opens the bot's Chrome profile (`browser_profile/`) for a one-time manual sign-in. Sign-in is checked through the results JSON `loggedIn` flag.
- Pacing: random `scan.delay_min_s`–`delay_max_s` between cards (doubled between pages), with `scan.max_new_jobs_per_run` as a cap. Searches live in `config/searches.yaml`.
- **Failure snapshots:** at 6 failure points (`goto_error`, `no_cards`, `dom_fallback`, `json_empty`, `no_description`, `human_timeout`) the scanner saves a PNG + HTML to `data/screenshots/` (`browser.save_snapshot`; the newest `browser.screenshots_keep` = 50 are kept) and prints the path. A page-load error stops the scan. Snapshots can hold the signed-in name/email, so scrub them before sharing.
- `decide_pending` (`pipeline.py`): an `LLMUnavailable` error (Ollama down / OOM / HTTP error / **timeout**, raised as `LLMTimeout`) **stops the run** and leaves jobs `new`. A per-job `LLMError` (bad JSON) marks just that job `failed`; `jobbot decide --retry-failed` re-queues failed jobs.

---

## Layout

Built so far:
- Step 1: `config.py`, `models.py`, `text.py`, `llm/`, `resumes/` (`library.py`, `parser.py`, `profiler.py`), `matcher/` (`filters.py`, `company_type.py`, `decide.py`) and `cli.py`.
- Step 2: `db.py` (SQLite `JobStore`), `pipeline.py` (`decide_pending`), `browser.py` (persistent headed Chrome + `wait_for_human`), `platforms/indeed/parse.py` (pure HTML/JSON parsing) and `platforms/indeed/scanner.py`.
- Tests: `tests/fixtures/jds/*.yaml` (sample JDs with an `expected:` block, used by `jobbot eval`) and `tests/fixtures/indeed/search_page.html` (a trimmed **real** Indeed results page).

The dashboard and the form filler are still planned.

Implementation notes:
- The LLM's `resume_id` / `role_track` are constrained by JSON-schema enums built from `resumes.yaml` (`decision_schema`). The code then post-checks the result: a score below the threshold downgrades it to skip, and `select_resume` enforces the role + company-type variant.
- The per-job prompt sends each resume's headline, core skills and domains only. Experience comes from `profile.yaml`, **not** from the LLM resume profile, which small models get wrong.
- Resume profiles are cached in `data/resume_profiles.json`, keyed by file sha256 + prompt version + model. Every decision is appended to `data/decisions.jsonl`.

```
local-llm-job-automate/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .gitignore
├── config/
│   ├── settings.example.yaml   # model name, daily caps, delays, thresholds
│   ├── searches.yaml           # Indeed saved searches (keyword × location)
│   └── mnc_companies.txt
├── documentation/              # spec-driven workflow docs (see "Development workflow")
│   ├── customer/
│   └── development/            # AI-DEVELOPMENT-WORKFLOW.md, architecture/, features/,
│                               # decisions/ (ADRs), standards/, changes/, templates/
├── .claude/rules/ , .claude/commands/
├── profile.example.yaml        # template for the user's form-answer facts
├── resumes/                    # gitignored: PDFs + resumes.yaml
├── data/                       # gitignored: jobs.db, logs, screenshots
├── browser_profile/            # gitignored: persistent Chrome profile
├── src/jobbot/
│   ├── config.py               # load + validate YAML (pydantic)
│   ├── db.py                   # SQLite JobStore + migration runner
│   ├── migrations/             # NNNN_*.sql schema migrations (the only schema record)
│   ├── llm/
│   │   ├── client.py           # Ollama client (OpenAI-compatible or native API)
│   │   └── prompts.py          # all prompt templates live here
│   ├── resumes/
│   │   ├── parser.py           # PDF/DOCX → text
│   │   └── profiler.py         # LLM → cached structured resume summary
│   ├── matcher/
│   │   ├── filters.py          # rule-based pre-filter
│   │   ├── company_type.py     # startup vs MNC resolution
│   │   └── decide.py           # LLM apply/skip + resume choice
│   ├── platforms/
│   │   └── indeed/
│   │       ├── scanner.py      # search + job detail scraping
│   │       └── applier.py      # Easily-apply form filler (stops pre-submit)
│   ├── answers.py              # screening question → profile answer mapping
│   ├── dashboard/app.py        # Streamlit review UI
│   └── cli.py                  # entry points
└── tests/
    └── fixtures/               # sample JDs + expected decisions
```

New job platforms go under `platforms/<name>/` and implement the same scanner/applier interface. Platform-specific code must not leak into `matcher/` or `llm/`.

---

## Build order

1. **Matcher first, no browser.** Resume parsing and profiling, then `decide` on pasted job descriptions, evaluated against `tests/fixtures/`. Prove accuracy and speed before touching Indeed.
2. **Indeed scanner:** searches, then job details, then the DB, then the matcher.
3. **Review dashboard** (Streamlit).
4. **Form filler** for Easily-apply jobs, stopping before Submit.

---

## Tech stack & conventions

- **Python 3.13**, `src/` layout, type hints everywhere, `pydantic` for config and LLM output models.
- **Playwright** (Python) using installed Chrome (`channel="chrome"`) with `launch_persistent_context`, **headed**.
- **SQLite** via the standard library `sqlite3` or SQLModel. Keep it simple; there is no server DB.
- **Ollama** at `http://localhost:11434`. Use structured output (`format` = JSON schema) for every decision call, and validate it with pydantic. On a parse failure, retry once, then mark the job `failed`. Never guess.
- **Streamlit** for the dashboard.
- Lint/format with `ruff`; test with `pytest`. LLM-dependent tests are marked `@pytest.mark.llm` and skipped by default.
- Prompts live only in `llm/prompts.py`. Version them (e.g. `DECIDE_PROMPT_V1`) and store the prompt version with each decision in the DB, so prompt changes can be compared.
- Log each LLM decision (inputs hash, output, latency) for later accuracy review.
- Selectors for Indeed live in one place per platform module. Expect Indeed's DOM to change and fail loudly with a screenshot saved to `data/screenshots/`.

---

## Environment notes

- **OS:** Windows 11. The shell is PowerShell, with Git Bash also available. Use `pathlib` for paths and avoid POSIX-only assumptions.
- **GPU:** RTX 4050 Laptop, **6 GB VRAM**. **RAM:** ~22 GB.
  - `gpt-oss:20b` (13 GB) runs mostly on CPU/RAM, with partial GPU offload. Expect slow but usable speed. Keep prompts short: send resume *summaries*, not full text, and truncate long job descriptions.
  - **Known issue (2026-11-21):** loading `gpt-oss:20b` failed with "out-of-memory during startup … failed to allocate CUDA_Host buffer". The cause is a tiny Windows page file: the commit limit is only ~25 GB, with ~5.5 GB free. The fix is a larger page file (user action, needs admin and a reboot). Don't "fix" this in code.
  - Don't run several LLM calls in parallel; process jobs one at a time.
  - A 7–8B model at 4-bit fits mostly or fully in VRAM and is a faster fallback. Switch models with `jobbot --model <name> ...` or `llm.model` in `config/settings.yaml`.
- Other local models present (`llama3.2`, `phi3`, `gemma3:270m`) are too small for reliable decisions. Use them only for plumbing tests. `llama3.2` scored 9/10 on the fixture eval at ~1.6s per call, but its resume profiles were wrong (it labelled 0.8 years of experience as "senior").
- The Ollama client drops the `think` option automatically for models without thinking support.

## Commands

The virtualenv is at `.venv` and was created with `uv`. On Windows, run tools via `.venv\Scripts\...` or activate the venv first. Set `PYTHONIOENCODING=utf-8` when piping output in Git Bash.

```powershell
uv venv .venv --python 3.13; uv pip install --python .venv\Scripts\python.exe -e ".[dev]"

jobbot resumes index [--force]         # parse + LLM-profile resumes (cached in data/)
jobbot resumes show                    # print cached profiles, no LLM
jobbot match path\to\jd.yaml           # decide one JD (.yaml with Job fields, or .txt + --title/--company/...)
jobbot eval [-v]                       # run all tests/fixtures/jds/*.yaml, compare with `expected`
jobbot login                           # one-time manual Indeed sign-in in the bot's Chrome profile
jobbot scan [-s NAME] [--pages N] [--decide]   # run searches -> data/jobs.db (opens visible Chrome)
jobbot decide [--limit N] [--retry-failed]     # LLM on all `new` jobs in the DB
jobbot jobs [--status pending_review]  # status counts + table
jobbot show ID                         # one job: decision + full description
jobbot --model llama3.2 eval           # same, with another Ollama model
pytest                                 # unit tests (no LLM)
ruff check src tests; ruff format src tests
```

Planned: `jobbot dashboard` (review UI), `jobbot fill` (fill approved jobs, stop before submit), `pytest -m llm`.
