# Architecture overview

jobbot is a single-user Python 3.13 package (`src/jobbot`) run from the command line. It has no
server and no accounts. Everything runs on the developer's Windows machine: a visible Chrome
driven by Playwright, a local Ollama server, and a SQLite file.

See also: [security.md](security.md), [data.md](data.md), the [ADRs](../decisions/README.md).

## Pipeline

```
SCAN ──▶ FILTER ──▶ DECIDE (LLM) ──▶ REVIEW (user) ──▶ FILL (bot) ──▶ SUBMIT (user)
 built     built       built            planned          planned        user only
```

| Stage | Who | What happens | Code |
|---|---|---|---|
| SCAN | bot | Run saved Indeed searches in a visible Chrome, store listings and full descriptions in SQLite, deduplicated by job key and description hash | `platforms/indeed/scanner.py`, `parse.py`, `browser.py`, `db.py` |
| FILTER | bot | Cheap rule-based rejects before any LLM call: experience far above the user's, senior titles, blacklists | `matcher/filters.py` |
| DECIDE | local LLM | Skip, or apply with a role track, company type and resume. JSON-schema output validated by pydantic, then post-checked in code | `matcher/decide.py`, `matcher/company_type.py`, `llm/`, `pipeline.py` |
| REVIEW | user | Approve, reject or change the resume in a dashboard | `dashboard/app.py` (planned) |
| FILL | bot | Open approved "Easily apply" jobs, upload the resume, answer screening questions from `profile.yaml`, **stop before Submit** | `platforms/indeed/applier.py`, `answers.py` (planned) |
| SUBMIT | user | The user clicks Submit. The bot detects the confirmation page and marks the job `applied` | (planned) |

`scan` and `decide` are separate commands so the browser doesn't sit open while a slow local
model thinks, and so scanning still works when the model can't load.

## Component diagram

```
                       ┌──────────────────────────── developer's machine ─────────────────────────────┐
                       │                                                                              │
  user ──▶ jobbot CLI (cli.py, Typer) ─────────┬───────────────────────┬──────────────────────┐       │
           dashboard (Streamlit, planned) ─┐   │                       │                      │       │
                       │                   ▼   ▼                       ▼                      ▼       │
                       │             pipeline.py ──▶ matcher/ ──▶ llm/client.py ──HTTP──▶ Ollama      │
                       │                   │        filters         prompts.py           localhost:11434
                       │                   │        company_type                                      │
                       │                   │        decide ◀── resumes/ (library, parser, profiler)   │
                       │                   ▼                         │                                │
                       │               db.py (JobStore) ◀────────────┼── migrations/*.sql             │
                       │                   │                         ▼                                │
                       │                   ▼                 data/resume_profiles.json                │
                       │             data/jobs.db            data/decisions.jsonl                     │
                       │                   ▲                                                          │
                       │                   │                                                          │
                       │   platforms/indeed/scanner.py ──▶ browser.py ──▶ Playwright ──▶ Chrome (headed,
                       │   platforms/indeed/parse.py                                     browser_profile/)
                       │   platforms/indeed/applier.py (planned)                               │      │
                       └────────────────────────────────────────────────────────────────────────┼──────┘
                                                                                                ▼
                                                                                   in.indeed.com (internet)
```

Only Chrome talks to the internet. The LLM, the data and the config never leave the machine.

## Module map

| Module | Responsibility |
|---|---|
| `cli.py` | Typer entry point `jobbot`: `resumes index/show`, `match`, `eval`, `login`, `scan`, `decide`, `jobs`, `show`, global `--model` |
| `config.py` | Paths (`PROJECT_ROOT`, `config/`, `resumes/`, `data/`, `profile.yaml`) and pydantic models: `Settings` (`llm`, `matching`, `browser`, `scan`), `Search`, `Profile`. Loads YAML |
| `models.py` | Platform-independent models: `Job`, `Decision` |
| `text.py` | Text normalisation, HTML to text |
| `db.py` | `JobStore` over SQLite: upsert listings, store descriptions (duplicate detection), save decisions, mark/reset failed, queries. Applies migrations from `migrations/` via `PRAGMA user_version` |
| `migrations/` | `NNNN_name.sql` schema files, shipped with the package ([ADR-0003](../decisions/ADR-0003-sql-migration-files.md)) |
| `pipeline.py` | `decide_pending`: runs the matcher over `new` jobs. `LLMUnavailable` stops the run; `LLMError` marks one job `failed` |
| `llm/client.py` | `OllamaClient.chat_json`: JSON-schema structured output, pydantic validation, one retry, `LLMError` / `LLMUnavailable` |
| `llm/prompts.py` | All prompt templates, with version constants (`RESUME_PROFILE_PROMPT_VERSION`, `DECIDE_PROMPT_VERSION`) |
| `resumes/library.py` | Loads `resumes/resumes.yaml` (role tracks, resume entries) |
| `resumes/parser.py` | PDF/DOCX/TXT to text |
| `resumes/profiler.py` | LLM resume summaries, cached in `data/resume_profiles.json` |
| `matcher/filters.py` | Rule-based pre-filter (experience, senior titles, blacklists) |
| `matcher/company_type.py` | startup vs MNC: MNC list, then company size, then LLM |
| `matcher/decide.py` | `Matcher`: filter, prompt, schema-constrained LLM call, post-checks (`min_score_to_apply`, `select_resume`), logs to `decisions.jsonl` |
| `browser.py` | Headed persistent Chrome (`launch_persistent_context`, `channel="chrome"`), `human_pause`, `wait_for_human` |
| `platforms/indeed/parse.py` | Pure parsing of Indeed pages. **All Indeed selectors and markers live here** |
| `platforms/indeed/scanner.py` | `IndeedScanner`: searches, card clicks, description reading, pacing, challenge/sign-in waits |
| `platforms/indeed/applier.py` | Planned: Easily-apply form filler, stops before Submit |
| `answers.py` | Planned: screening question to `profile.yaml` answer mapping, LLM fallback flagged |
| `dashboard/app.py` | Planned: Streamlit review queue |

Boundaries:
- Platform-specific code stays in `platforms/<name>/`. It must not leak into `matcher/` or `llm/`.
- New platforms add `platforms/<name>/` with the same scanner/applier interface.
- Prompts live only in `llm/prompts.py`.

## Capabilities

| Capability | Status | Covers | Spec |
|---|---|---|---|
| `resume-matcher` | Built (step 1) | resume library + profiling, filters, company type, LLM decide, `match`, `eval` | [features/resume-matcher](../features/resume-matcher/) |
| `indeed-scanner` | Built (step 2) | `login`, `scan`, Indeed parsing, headed browser, human waits | [features/indeed-scanner](../features/indeed-scanner/) |
| `job-store` | Built (step 2) | SQLite `JobStore`, migrations, status lifecycle, `decide` over the DB, `jobs`, `show` | [features/job-store](../features/job-store/) |
| `review-dashboard` | Planned (step 3) | Streamlit review queue: approve / reject / change resume | no spec yet |
| `form-filler` | Planned (step 4) | Fill approved Easily-apply forms, stop before Submit, daily cap, detect confirmation | no spec yet |

## Runtime environment

- Windows 11, PowerShell or Git Bash. Use `pathlib`; no POSIX-only assumptions.
- RTX 4050 (6 GB VRAM), ~22 GB RAM. `gpt-oss:20b` runs mostly on CPU, so LLM calls are slow and
  run **one at a time**. A 7–8B model is the faster fallback (`jobbot --model <name>`).
- Ollama at `http://localhost:11434`.
