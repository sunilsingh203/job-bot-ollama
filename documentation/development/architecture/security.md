# Security and safety

jobbot is a local, single-user tool. There is no server, no account system and no session of our
own, so web-application controls (RBAC, CSRF, cookies) don't apply. The real risks are:
personal data leaving the machine, harming the user's Indeed account, sending an application the
user didn't approve, putting false facts on a form, and trusting input we don't control.

The non-negotiable rules in `CLAUDE.md` are the source of truth. This page explains them as a
threat model. Short agent rules: `.claude/rules/safety.md`.

## Assets

| Asset | Where | Why it matters |
|---|---|---|
| Resumes | `resumes/` | Personal data (name, contact details, history) |
| Candidate facts | `profile.yaml` | Personal data: location, CTC, notice period, form answers |
| Indeed session | `browser_profile/` | Effectively a credential: cookies for the user's Indeed account |
| Job data and decisions | `data/jobs.db`, `data/decisions.jsonl` | Job search history |
| Resume summaries | `data/resume_profiles.json` | Derived from resumes |
| Screenshots | `data/screenshots/` | May show personal data on forms |
| Local settings | `config/settings.yaml` | Personal tuning; may name blacklisted companies |

## Threats and controls

| # | Threat | Control |
|---|---|---|
| T-1 | Personal data or job data sent to a cloud service | Only the local Ollama server (`llm.base_url`, localhost) is used. No cloud LLM APIs, analytics or telemetry. New dependencies are checked for phone-home behaviour. ([ADR-0001](../decisions/ADR-0001-local-only-llm.md)) |
| T-2 | Personal data committed to Git | `.gitignore` covers `resumes/*` (except the example), `profile.yaml`, `config/settings.yaml`, `data/`, `browser_profile/`. Only `*.example.yaml` templates are committed. Review every diff for personal data |
| T-3 | An application is submitted without the user | The bot never clicks Submit. It stops on Indeed's final review page. Any future auto-submit path needs the developer's explicit request and a config flag defaulting to `false` ([ADR-0004](../decisions/ADR-0004-human-approval-never-auto-submit.md)) |
| T-4 | Indeed flags or bans the account | Visible (headed) real Chrome with a dedicated persistent profile; random human-like delays; caps per run (`scan.max_new_jobs_per_run`) and per day for fills (planned, default ~25) |
| T-5 | Login automation or credential storage | Never script the Indeed login, never store passwords. `jobbot login` only opens the window; the user signs in by hand |
| T-6 | Bypassing bot checks | Never try to bypass CAPTCHAs or Cloudflare. Detect them (`is_challenge`, `is_signin` in `parse.py`), pause and wait for the user (`browser.wait_for_human`) |
| T-7 | False facts on an application form | Answers come from `profile.yaml`. An LLM-written answer to an unknown question is marked **LLM-generated** so the user checks it before Submit |
| T-8 | Prompt injection from job descriptions | A JD is untrusted text placed in the prompt as data. The LLM can only return JSON that matches the schema; `role_track` and `resume_id` are enums built from `resumes.yaml`. Code post-checks the result (score threshold, `select_resume`). The LLM never triggers actions directly: an "apply" only queues the job for human review |
| T-9 | Malformed or hostile scraped HTML/JSON | Parsing is pure and defensive (`parse.py`), with a DOM fallback; it fails loudly (planned: screenshot to `data/screenshots/`) rather than guessing. Scraped values are stored as text |
| T-10 | SQL injection via scraped strings | All queries use `sqlite3` parameters. Never format scraped or user values into SQL |
| T-11 | Bad LLM output treated as truth | `OllamaClient.chat_json` validates with pydantic, retries once, then raises; the job is marked `failed`. Never guess |
| T-12 | Ollama or the dashboard reachable from the network | Ollama is used at `localhost:11434`. Don't expose it on `0.0.0.0`. The planned Streamlit dashboard must bind to `localhost` |
| T-13 | Path tricks from config | Resume ids are validated (lowercase letters, digits, `_`, `-`). Resume files are joined to `resumes/` (`ResumeLibrary.path_of`) but not yet checked to stay inside it; low risk because only the user writes `resumes.yaml`. Never build file paths from scraped or LLM text |
| T-14 | Personal data in logs | `decisions.jsonl` stores job fields and the decision, not resume text or `profile.yaml`. Don't log profile values, cookies or page HTML outside `data/` |

## Blueprint security items that don't apply

| Blueprint item | Why it's N/A |
|---|---|
| Backend-enforced authorization, user/role/permission model | One local user, no server, no roles |
| Data scope by branch/tenant/owner | One user's own data on their own machine |
| Actor identity from the session | No sessions; the one local user is the actor |
| Server-side sessions, HttpOnly/Secure/SameSite cookies, CSRF, CORS | We run no web server with sessions. Streamlit (planned) is local-only. The Indeed session is Chrome's, kept in `browser_profile/` and never read by our code |
| Safe API error model | No API. CLI errors should be clear and must not print personal data |

## Approval flow (maker-checker, adapted)

The bot is the "maker", the user is the "checker":

1. `decide` proposes: `pending_review` (Easily apply) or `manual` (external apply).
2. The user approves, rejects or changes the resume in the dashboard (planned).
3. The bot fills only `approved` jobs and stops at `ready_to_submit`.
4. The user clicks Submit. The bot only detects the confirmation and records `applied`.

Status changes are made through `JobStore` (`db.py`). When the review and fill steps are built,
the allowed transitions must be checked there, not only hidden in the UI.

## When in doubt

If a change touches any of the controls above, stop and ask the developer. Don't weaken a control
to make something work.
