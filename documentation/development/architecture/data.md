# Data

All data lives on the developer's machine. Personal and runtime data is gitignored
(see [What is gitignored](#what-is-gitignored-and-why)).

## SQLite: `data/jobs.db`

Opened by `JobStore` (`src/jobbot/db.py`). The schema is defined only by the migration files in
`src/jobbot/migrations/NNNN_name.sql`. `JobStore` applies every file whose number is higher than
`PRAGMA user_version`, in order, and then sets `user_version` to that number
([ADR-0003](../decisions/ADR-0003-sql-migration-files.md)). Schema version 1 (`0001_init.sql`) is the `jobs` table below.

### Table `jobs`

One row per platform job, plus its latest decision.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PK | Local id, used by `jobbot show ID` |
| `platform` | TEXT NOT NULL | e.g. `indeed` |
| `job_key` | TEXT NOT NULL | The platform's job id (Indeed `jk`) |
| `url` | TEXT | Job URL |
| `title`, `company`, `location` | TEXT NOT NULL DEFAULT '' | From the search results |
| `description` | TEXT | Full job description (read from the right-hand pane). NULL until fetched |
| `description_sha256` | TEXT | Hash of `description`, used to detect duplicate postings |
| `snippet` | TEXT | Short snippet from the results page |
| `salary` | TEXT | Salary text as shown |
| `posted_at` | TEXT | ISO date |
| `easy_apply` | INTEGER (0/1/NULL) | Indeed "Easily apply" (`indeedApplyEnabled`) |
| `remote` | INTEGER (0/1/NULL) | Remote listing |
| `company_size` | TEXT | e.g. "10,000+ employees", when known |
| `search_name` | TEXT | The `config/searches.yaml` search that first found it |
| `status` | TEXT NOT NULL DEFAULT 'new' | See the lifecycle below |
| `decision` | TEXT | `apply` / `skip` |
| `resume_id` | TEXT | Chosen resume id from `resumes.yaml` |
| `score` | INTEGER | LLM score 0–100 |
| `reason` | TEXT | Short reason |
| `decision_json` | TEXT | Full `Decision` model as JSON (includes `stage`, `role_track`, `company_type`, `notes`, `model`, `prompt_version`, `latency_s`) |
| `error` | TEXT | Last error (failed decision, duplicate of job #N) |
| `first_seen_at`, `updated_at`, `decided_at` | TEXT | ISO timestamps (local time, seconds) |

Constraints and indexes: `UNIQUE (platform, job_key)`, `idx_jobs_status (status)`,
`idx_jobs_desc (description_sha256)`.

Columns for review and fill (approval time, edited resume, fill results, LLM-generated answers)
will be added by migrations when `review-dashboard` and `form-filler` are built.

### Status lifecycle

```
                    ┌──▶ filtered_out    (rule filter rejected it)
                    ├──▶ skipped         (LLM said skip, or post-checks downgraded it)
 new ──(decide)─────┼──▶ pending_review  (apply + Easily apply)
  │                 ├──▶ manual          (apply, but external "Apply on company site")
  │                 └──▶ failed ──(decide --retry-failed)──▶ new
  └──(same description as another job)──▶ duplicate

 pending_review ──▶ approved ──▶ filling ──▶ ready_to_submit ──▶ applied        (planned)
                └─▶ rejected
```

| Status | Set by | Meaning |
|---|---|---|
| `new` | `upsert_listing`, `set_description`, `reset_failed` | Waiting for a decision (decided only once `description` is set) |
| `duplicate` | `set_description` | Same description hash as an existing job |
| `filtered_out` | `save_decision` (`stage == "filter"`) | Rejected by `matcher/filters.py` |
| `skipped` | `save_decision` | LLM skip, or apply downgraded (low score, no role track, no resume) |
| `pending_review` | `save_decision` | Apply, Easily apply: waits for the user |
| `manual` | `save_decision` | Apply, external apply: the user applies on the company site |
| `failed` | `mark_failed` | Bad LLM output (invalid JSON) after one retry. `LLMUnavailable`, including a timeout (`LLMTimeout`), does not mark jobs; the run stops |
| `approved` / `rejected` | dashboard (planned) | The user's review |
| `filling` / `ready_to_submit` | form filler (planned) | Bot fills, stops before Submit |
| `applied` | form filler (planned) | Confirmation page detected after the user clicked Submit |

## Files in `data/`

| File | Written by | Contents |
|---|---|---|
| `jobs.db` | `JobStore` | The table above |
| `resume_profiles.json` | `resumes/profiler.py` | Cache of LLM resume summaries, keyed by resume id. Each entry: `sha256` of the file, `file`, `prompt_version`, `model`, `profile` (`headline`, `total_experience_years`, `seniority`, `core_skills`, `other_skills`, `domains`, `highlights`, `summary`). An entry is rebuilt when the file hash, prompt version or model changes. Stale ids are dropped |
| `decisions.jsonl` | `matcher/decide.py` (`Matcher._log`) | Append-only, one JSON object per decision: `ts`, `job` (`title`, `company`, `location`, `url`, `platform`, `description_sha256`) and `decision` (the full `Decision` model, incl. `model`, `prompt_version`, `latency_s`). Used for accuracy review and prompt comparisons |
| `screenshots/` | `browser.save_snapshot`, called by the scanner (`platforms/indeed/scanner.py`) at its failure points; the planned form filler can reuse it | Failure snapshot sets `<YYYYMMDD-HHMMSS-mmm>_<reason>[_<jobkey>].png` + `.html` (local time; full-page PNG; page HTML as UTF-8). Reasons: `goto_error`, `no_cards`, `dom_fallback`, `no_description` (with the sanitised job key, `[A-Za-z0-9]{1,32}`), `human_timeout`. After each save only the newest `browser.screenshots_keep` (default 50) sets are kept; files not matching that name pattern are never touched. **May contain the signed-in name/email and session tokens:** never share, commit or turn into a fixture without scrubbing |

## Configuration and personal input files

| File | Committed? | Contents |
|---|---|---|
| `config/settings.example.yaml` | yes | Documented defaults for `llm`, `matching`, `browser`, `scan` (incl. `browser.screenshots_keep`: newest failure snapshot sets kept, int >= 1, default 50) |
| `config/settings.yaml` | **no** | The user's overrides (every key optional); validated by `config.Settings` |
| `config/searches.yaml` | yes | Indeed searches (`name`, `query`, `location`, `max_pages`, `fromage`, `sort`, `extra_params`) |
| `config/mnc_companies.txt` | yes | User-maintained MNC list (first source for company type) |
| `profile.example.yaml` | yes | Template |
| `profile.yaml` | **no** | The candidate's facts (`total_experience_years`, location, remote/relocate, notice period, CTC, extra keys for form answers) |
| `resumes/resumes.example.yaml` | yes | Template |
| `resumes/resumes.yaml` + resume files | **no** | `role_tracks` and resume entries (`id`, `file`, `roles`, `company_type`, `notes`) |
| `tests/fixtures/` | yes | Sample JDs with `expected:` blocks; a trimmed real Indeed results page. Must contain no personal data |

## What is gitignored and why

| Path | Why |
|---|---|
| `resumes/*` (except `resumes.example.yaml`) | Personal documents |
| `profile.yaml` | Personal facts used on forms |
| `config/settings.yaml` | Personal tuning and blacklists |
| `data/` | Job history, decisions, resume summaries, screenshots |
| `browser_profile/` | Indeed session cookies: treat as a credential |
| `.venv/`, caches | Build artefacts |

## Backups and destructive changes

`data/jobs.db` is the only copy of the job history. Before a destructive migration (drop, status
rewrite, bulk delete), get the developer's approval and suggest copying `data/jobs.db` first.
