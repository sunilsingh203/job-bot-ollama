# Specification: `resume-matcher` (Step 1)

Status: As-built — documented retroactively on 2026-11-26 from the existing code. Awaiting review by the approver (approval: by the developer, by hand or recorded from chat — ADR-0005).

- Lane: A (new capability), documented after the fact
- Governance level: standard
- Code: `src/jobbot/` (initial commit `c3677ba`)
- Related: `implementation-plan.md`, `changelog.md` in this folder; ADR-0001-local-only-llm in `documentation/development/decisions/`

This document describes what the code **currently does**. Where the code differs from `CLAUDE.md`, or looks unclear or risky, the point is listed under [Open questions & assumptions](#open-questions--assumptions). Nothing here changes the code.

---

## 1. Purpose

Given one job description (JD), decide **apply** or **skip**. On apply, also pick the **one resume** from the user's resume library that fits the job best. The resume choice depends on the job's **role track** (for example `sde`, `java`, `devops`) and the **company type** (`startup` / `mnc`).

The matcher runs fully offline against a local Ollama model and never opens a browser. It is the decision engine that later steps (Indeed scanning, the review dashboard, the form filler) call for each job. Cheap rule-based filters run first, so the slow local LLM only sees jobs that could plausibly fit.

## 2. Actors

| Actor | Role in this capability |
|---|---|
| **Developer / operator** (the single local user) | Maintains `resumes/resumes.yaml`, `profile.yaml`, `config/settings.yaml` and `config/mnc_companies.txt`. Runs `jobbot resumes index/show`, `jobbot match` and `jobbot eval`. Reads decisions and the `decisions.jsonl` log. |
| **Local Ollama LLM** (default `gpt-oss:20b`, configurable) | (a) Builds a structured profile of each resume once (cached). (b) For each job that passes the filters, returns a schema-constrained JSON decision. It is treated as fallible: every output is schema-validated and then post-checked in code. |
| **Resume library** (`resumes/resumes.yaml` + resume files) | The set of resumes the matcher may choose from. Each entry has an id, a file, the role tracks it serves and its company type. It also defines the role tracks that are shown to the LLM. |
| *(consumer)* Step 2 pipeline (`pipeline.decide_pending`) | Calls `Matcher.decide(job)` for jobs stored in SQLite and maps the result to job statuses. This is outside this capability (see Dependencies). |

## 3. Scope

In scope:
- Loading and validating settings, the candidate profile, the MNC list and the resume library (`config.py`, `resumes/library.py`)
- Extracting resume text from PDF / DOCX / TXT / MD files (`resumes/parser.py`)
- LLM-built structured resume profiles, cached on disk (`resumes/profiler.py`)
- Rule-based pre-filters: blacklists, senior titles, required experience (`matcher/filters.py`)
- Company-type resolution: MNC list, then company size, then the LLM (`matcher/company_type.py`, `matcher/decide.py`)
- The LLM apply/skip decision with a schema-constrained output, plus deterministic post-checks and resume selection (`matcher/decide.py`)
- The Ollama client with JSON validation, one retry and error classification (`llm/client.py`)
- Versioned prompt templates (`llm/prompts.py`)
- Appending every decision to `data/decisions.jsonl`
- CLI commands: `jobbot resumes index [--force]`, `jobbot resumes show`, `jobbot match`, `jobbot eval [-v]`, and the global `--model` option
- The JD fixture set `tests/fixtures/jds/*.yaml`, used by `jobbot eval`

## 4. Out of scope

- Indeed scanning, the browser, the SQLite job store and job statuses (Step 2: `db.py`, `pipeline.py`, `platforms/`)
- The review dashboard (Step 3) and the form filler / screening answers (Step 4)
- Generating cover letters or free text
- Writing or tailoring resumes. The matcher only *chooses* among existing files.
- "Already applied" detection. This belongs to the job store, not the matcher (see OQ-1).
- Location filtering (see OQ-1)
- Any cloud LLM, analytics or network call other than the configured Ollama endpoint

---

## 5. Business rules

### BR-1 Rule-based filters run first (`matcher/filters.py:49-76`)

`check_filters(job, profile, matching_settings)` checks the following in this order and **returns at the first failure**:

| # | Rule | Match semantics | Config (`matching.*`, defaults) |
|---|---|---|---|
| 1 | Blacklisted company | Case-insensitive **substring** of `job.company` (`filters.py:50-53`) | `blacklist_companies: []` |
| 2 | Blacklisted keyword | Case-insensitive **whole word** (`\b…\b`) in `title + "\n" + description` (`filters.py:55-58`) | `blacklist_keywords: []` |
| 3 | Senior title | Applies only when `profile.total_experience_years < senior_title_min_experience`. Any keyword as a whole word in `job.title` rejects the job (`filters.py:60-66`). | `senior_title_min_experience: 4.0`, `senior_title_keywords: [senior, sr, lead, principal, staff, architect, manager, head, director, vp]` |
| 4 | Required experience | Rejects when `required_experience(description) > profile years + experience_tolerance_years` (strictly greater) (`filters.py:68-75`) | `experience_tolerance_years: 2.0` |

`required_experience(text)` (`filters.py:28-42`):
- Matches patterns like `3+ years`, `3-5 yrs`, `2 to 4 years`, `5 plus years` (`_EXP_RE`, `filters.py:13-16`). For a range, only the **lower** number counts.
- A match counts only if `exp` (case-insensitive) appears within 50 chars before or 60 chars after it (`filters.py:36-38`).
- Values above 25 are ignored as implausible (`_MAX_PLAUSIBLE_YEARS`, `filters.py:18`).
- The result is the **highest** of the remaining minimums ("3+ yrs Java, 1+ yr AWS" gives 3), or `None` when no experience number is found.
- Only the description is scanned, not the title.

The filter result always carries `required_experience_years` (also on pass), and it is copied into the `Decision`.

### BR-2 Company type resolution order (`matcher/company_type.py:47-55`, `matcher/decide.py:126-163`)

1. **MNC list.** `config/mnc_companies.txt` lists one name per line; blank lines and `#` comments are ignored (`config.py:155-160`), and a missing file gives an empty list. Both names are normalized: lowercased, `&` becomes "and", common suffixes are removed (pvt, ltd, limited, inc, india, technologies, solutions, services, software, global, group, …), non-alphanumerics are stripped (`company_type.py:13-24`). A match means the names are equal, or the job's company **starts with** the list entry followed by a space (`company_type.py:27-36`). Result: `("mnc", "mnc_list")`.
2. **Company size.** The first integer in `job.company_size` (commas removed), i.e. the lower bound (`company_type.py:39-44`). `>= matching.mnc_min_employees` (default 1000) gives `mnc`, otherwise `startup`. Source: `company_size`.
3. **LLM.** If both above are unknown, the prompt says "Unknown. Infer startup or mnc…" and the LLM's `company_type` is used, with source `llm`. If the LLM also says `unknown`, the result is `unknown` / `unknown`.

When the type is known from data, the prompt says `Known: <type> (from <source>). Use this value.` and the code **ignores the LLM's `company_type`**, keeping the data value (`decide.py:158`).

### BR-3 LLM decision contract (`matcher/decide.py:26-42`, `llm/prompts.py:28-65`)

The LLM must return JSON matching `LLMDecision`. The field order is deliberate: the reason is written before the verdict.

```json
{"reason": "1-2 sentences",
 "role_track": "<one of resumes.yaml role_tracks> | none",
 "company_type": "startup | mnc | unknown",
 "resume_id": "<one of resumes.yaml ids> | none",
 "score": 0-100,
 "decision": "apply | skip"}
```

- `decision_schema(library)` adds JSON-schema `enum`s for `role_track` (role track keys + `"none"`) and `resume_id` (resume ids + `"none"`). The schema is passed to Ollama as `format`. Adding a resume or track in `resumes.yaml` therefore changes the allowed values without a code change.
- `score` is validated by pydantic as `0 <= score <= 100`. `company_type` and `decision` are pydantic `Literal`s. `role_track` and `resume_id` are plain `str` in pydantic; only Ollama's grammar enforces their enums (see OQ-4).

### BR-4 Deterministic post-checks after the LLM (`matcher/decide.py:165-182`)

These are applied in order to the LLM's verdict:
1. `apply` with `score < matching.min_score_to_apply` (default **60**) becomes **skip**, with the note `LLM said apply but score S < 60`.
2. `apply` with `role_track == "none"` becomes **skip**, with the note `LLM said apply but role_track is 'none'`.
3. If the verdict is still `apply`, run `select_resume` (BR-5). If that returns no resume, the verdict becomes **skip** with the note `No resume matches this role track`.

An LLM `skip` is never upgraded to apply, whatever the score. On a final `skip`, `resume_id` is `None`, even if the LLM named one.

### BR-5 Resume selection: role track × company type (`matcher/decide.py:45-64`)

`select_resume(library, role_track, company_type, llm_choice)`:
1. `candidates` are the resumes whose `roles` contain `role_track`.
2. If there are **no candidates**, keep `llm_choice` if it is a real resume id, otherwise `None`. No note is added.
3. Otherwise the preferred list is the **first non-empty** of these:
   - resumes with `company_type == company_type` (exact variant)
   - resumes with `company_type == "any"`
   - all candidates (for example, only an MNC variant exists for a startup job)
4. If `llm_choice` is in the preferred list, keep it. Otherwise use the **first** preferred resume (in `resumes.yaml` order) and add the note `Resume changed from '<llm>' to '<chosen>' (role=…, company=…)`.

With `company_type == "unknown"` no resume matches exactly, so `any` resumes are preferred, and after that all candidates.

### BR-5a Resume prompt context

The per-job prompt lists each resume as its id, tracks, company type, plus the cached profile's **headline, core skills, domains** and the optional `notes` from `resumes.yaml` (`decide.py:67-81`). The full resume text is never sent per job.

### BR-6 Candidate experience comes from `profile.yaml`, not from the LLM

- The prompt's `Total professional experience` comes from `profile.total_experience_years`, alongside location, remote and relocate (`decide.py:135-140`).
- The filters also use `profile.total_experience_years`.
- `ResumeProfile.total_experience_years` and `seniority` (made by the LLM) are stored in the cache and shown by `jobbot resumes show`, but are **never used for a decision**. This is a deliberate choice: small models misjudge experience (CLAUDE.md records `llama3.2` labelling 0.8 years as "senior").

### BR-7 Job description truncation

`job.description` is cut to `llm.max_jd_chars` (default 6000) characters before the LLM call. When truncation happens, the note `JD truncated to N chars for the LLM` is added (`decide.py:134, 155-156`). The filters run on the **full** description.

### BR-8 Retry once, then fail; never guess (`llm/client.py:49-95`)

- Each LLM call sends `format = <JSON schema>`, `stream = false`, `temperature` (default 0.0), `num_ctx` (default 8192), and `think` (default `"low"`, left out when `null`).
- The response `message.content` is validated with `output_model.model_validate_json`. On a `ValidationError` (bad JSON or schema mismatch) the call is retried **once**, with temperature `max(temperature, 0.3)`. After 2 invalid answers it raises `LLMError("Model returned invalid JSON after 2 attempts: …")`. There is no fallback value or heuristic guess.

### BR-9 Resume profile caching (`resumes/profiler.py:53-111`)

- Cache file: `<data_dir>/resume_profiles.json`, keyed by resume id. Each entry holds `{sha256, file, prompt_version, model, profile}`.
- An entry is **fresh** when the file's sha256, `RESUME_PROFILE_PROMPT_VERSION` (`resume_profile_v1`) and the current model name all match. Fresh entries are reused. Otherwise (or with `--force`) the resume is re-extracted and re-profiled.
- Entries for ids no longer in `resumes.yaml` are deleted. The file is rewritten only if something changed.

### BR-10 Decision logging (`matcher/decide.py:110-113, 200-215`)

Every successful `Matcher.decide()` call, at either stage (filter or LLM), appends one JSON line to `<data_dir>/decisions.jsonl` (see Data entities). Calls that raise an exception are not logged.

### BR-11 Model override

`jobbot --model <name> …` sets the env var `JOBBOT_MODEL`, which `load_settings()` applies over `llm.model` (`cli.py:42-49`, `config.py:141-143`).

### BR-12 Prompt hygiene

`DECIDE_SYSTEM` tells the model that the JD is untrusted and that instructions inside it must be ignored (`prompts.py:30-34`). The JD is wrapped in `<<< >>>` delimiters.

---

## 6. Data entities

All entities are pydantic models unless noted. None are persisted in SQLite by this capability.

### Job (`models.py:11-27`)
| Field | Type | Notes |
|---|---|---|
| `title`, `company`, `location` | str, default `""` | `title` is used by the senior-title and keyword filters |
| `description` | str (**required**) | Full JD text |
| `company_size` | str \| None | e.g. `"10,000+ employees"`; input to company-type step 2 |
| `url`, `platform`, `job_key` | str \| None | Passed through to the log |
| `easy_apply`, `remote` | bool \| None | Not used by the matcher (the Step 2 status mapping uses `easy_apply`) |
| `salary`, `posted_at` | str \| None | Not used by the matcher |
| `description_sha256` | property | sha256 of `description` (UTF-8) |

### Decision (`models.py:30-43`): matcher output
| Field | Type | Filled when |
|---|---|---|
| `decision` | `apply` \| `skip` | always |
| `stage` | `filter` \| `llm` | always: which step made the call |
| `reason` | str | filter reason, or the LLM's reason |
| `resume_id` | str \| None | only on a final `apply` |
| `role_track` | str \| None | LLM stage; `None` when the LLM said `none` |
| `company_type` | `startup` \| `mnc` \| `unknown` | LLM stage (filter stage: `unknown`) |
| `company_type_source` | str | `mnc_list` \| `company_size` \| `llm` \| `unknown` |
| `score` | int \| None | LLM stage |
| `notes` | list[str] | post-check adjustments (truncation, downgrade, resume override) |
| `required_experience_years` | float \| None | both stages, from `required_experience()` |
| `model`, `prompt_version`, `latency_s` | | LLM stage only (`prompt_version = "decide_v1"`) |

### LLMDecision (`matcher/decide.py:26-33`)
The raw LLM output contract (BR-3). It is not persisted; only the derived `Decision` is.

### Resume library (`resumes/library.py:15-36`), file `resumes/resumes.yaml` (gitignored)
- `role_tracks: dict[str, str]` (at least 1): track id → description shown to the LLM
- `resumes: list[ResumeEntry]` (at least 1). Each `ResumeEntry` has:
  - `id`: matches `^[a-z0-9_\-]+$`, unique
  - `file`: relative to `resumes/`, must exist
  - `roles`: list with at least 1 entry, each a key of `role_tracks`
  - `company_type`: `startup | mnc | any`, default `any`
  - `notes`: str, shown to the LLM if not empty
- `base_dir` is injected at load time (not read from YAML).
- Template: `resumes/resumes.example.yaml`.

### ResumeProfile (`resumes/profiler.py:27-35`): cached LLM summary
`headline`, `total_experience_years` (float), `seniority` (`intern|entry|mid|senior|lead`), `core_skills` (max 20), `other_skills`, `domains`, `highlights` (max 6), `summary`.

### Resume profile cache (`data/resume_profiles.json`, gitignored)
`{ "<resume_id>": { "sha256": str, "file": str, "prompt_version": str, "model": str, "profile": ResumeProfile } }`

### Decision log (`data/decisions.jsonl`, gitignored, append-only)
One JSON object per line:
`{ "ts": "YYYY-MM-DDTHH:MM:SS", "job": {title, company, location, url, platform, description_sha256}, "decision": <Decision.model_dump()> }`

### Configuration inputs
- `Settings.llm` (`config.py:23-31`): `base_url` (`http://localhost:11434`), `model` (`gpt-oss:20b`), `temperature` (0.0), `num_ctx` (8192), `think` (`"low"`), `timeout_s` (600), `max_jd_chars` (6000)
- `Settings.matching` (`config.py:34-54`): see BR-1 and BR-2, plus `min_score_to_apply` (60)
- `Profile` (`config.py:107-120`, file `profile.yaml`, gitignored): `total_experience_years` (**required**), `current_location`, `open_to_remote`, `open_to_relocate` are used by the matcher. `preferred_locations`, notice period and CTC fields are loaded but not used by the matcher. Extra keys are allowed for later form-filling.
- `config/settings.yaml` is optional (gitignored). If it is absent, all defaults apply; `config/settings.example.yaml` documents every key.

---

## 7. States / outcomes

The matcher is stateless per job: one call to `Matcher.decide(job)` gives exactly one outcome.

| Outcome | `decision` | `stage` | LLM called? | `resume_id` |
|---|---|---|---|---|
| Filter reject | `skip` | `filter` | No | `None` |
| LLM skip (incl. downgrades from BR-4) | `skip` | `llm` | Yes | `None` |
| LLM apply | `apply` | `llm` | Yes | a valid library id |
| Error | (none; an exception is raised) | n/a | maybe | n/a |

For reference only (owned by Step 2, `db.status_for`, `db.py:130-135`): `stage=filter` maps to `filtered_out`, `skip` to `skipped`, `apply` with Easily-apply to `pending_review`, other `apply` to `manual`. An `LLMError` maps to `failed`, and `LLMUnavailable` stops the run.

## 8. Permissions & data scope

- **Single local user.** There are no accounts, roles or authentication. Whoever can run `jobbot` on the machine can see all data.
- **Everything stays local** (CLAUDE.md rule 2; ADR-0001-local-only-llm). The only network traffic is HTTP to `llm.base_url` (default `http://localhost:11434`, Ollama native `/api/chat`). The code does not enforce that `base_url` is local (see OQ-15).
- **Personal data is gitignored** (`.gitignore`): `resumes/*` except `resumes.example.yaml`, `profile.yaml`, `config/settings.yaml`, `data/` (holds `resume_profiles.json` and `decisions.jsonl`). Only the `*.example.yaml` templates and `config/mnc_companies.txt` are committed.
- `decisions.jsonl` stores job metadata and LLM reasons, but no resume text and no profile facts. `resume_profiles.json` stores LLM summaries of the resumes, which are personal data and stay under `data/`.

## 9. Validation rules

| Input | Validation | On failure |
|---|---|---|
| `config/settings.yaml` | pydantic `Settings`; invalid YAML is caught | `ConfigError("Invalid YAML in …")`. Note: a pydantic `ValidationError` on settings is **not** wrapped (see OQ-12) |
| `profile.yaml` | must exist; `total_experience_years` required | `ConfigError("… not found. Copy profile.example.yaml …")` / pydantic `ValidationError` |
| `resumes/resumes.yaml` | must exist; schema (id pattern, at least 1 role, at least 1 resume, at least 1 track, company_type enum); unique ids; every file exists; every role is a defined track | `ConfigError` listing **all** problems (`library.py:39-64`) |
| Resume file format | `.pdf`, `.docx`, `.txt`, `.md` only | `ValueError("Unsupported resume format …")` at profiling time (`parser.py:22-23`) |
| Resume profiles present | each library id needs a profile to build a `Matcher` | `ValueError("No profile for resumes […]. Run `jobbot resumes index` first.")` (`decide.py:96-98`) |
| LLM output | JSON schema via Ollama `format`, then pydantic validation (`LLMDecision` / `ResumeProfile`) | one retry, then `LLMError` |
| JD file for `match` / `eval` | `.yaml`/`.yml` is validated as `Job` (an `expected` block is removed first); any other suffix is read as plain-text description | pydantic `ValidationError` (not caught nicely in `match`, see OQ-12) |

## 10. Error cases

| Error | Raised by | Meaning | Caller behaviour |
|---|---|---|---|
| `LLMUnavailable` (subclass of `LLMError`) | `client._post`: `httpx.ConnectError`, or any HTTP status other than 200 (after the `think` fallback) (`client.py:101-112`) | Ollama down, model missing, model cannot load (e.g. OOM returned as an HTTP error) | CLI prints `Error:` and exits 1. Step 2 `decide_pending` **stops the run**. |
| `LLMError` | `chat_json` after 2 invalid outputs; `httpx.TimeoutException` (`client.py:95, 105-106`) | One bad answer, or a timeout for one call | CLI prints `Error:` and exits 1 (in `eval`, this aborts the whole eval). Step 2 marks just that job `failed`. |
| HTTP 400 mentioning "thinking" with `think` set | `client._post` (`client.py:107-110`) | Model has no thinking mode | Retried once automatically without `think`; not surfaced |
| `ConfigError` | config/library loaders | Missing or invalid config file | CLI prints the message and exits 1 |
| `ValueError` | parser (unsupported format), `Matcher.__init__` (missing profiles) | | Caught by `match`/`eval` (`Error:`). In `resumes index` an unsupported format is **not** caught, so a traceback is shown (OQ-12). |
| Unknown `resume_id` from the LLM | n/a (handled) | LLM named a resume outside the preferred set, or `none` | `select_resume` replaces it with the first preferred resume and adds a note; if no candidate is valid, the result is skip |
| Missing resume file | `load_library` | | `ConfigError: resume '<id>': file not found: …` |
| Missing `mnc_companies.txt` | `load_mnc_list` | | Not an error: empty list, so resolution falls through to company size / LLM |

---

## 11. Acceptance criteria (current behaviour)

Reference profile for the examples: `total_experience_years = 0.8`, default `matching` settings.

**Filters**

- **AC-1** `required_experience(text)` returns the highest *minimum* years among experience phrases (`N+ years`, `N-M yrs`, `N to M years`, `N plus years`) that have `exp` within the context window. It returns `None` for text without such phrases, for unrelated numbers ("Founded 10 years ago"), and for values above 25.
  Verified by: tests/test_filters.py::test_required_experience
- **AC-2** A job whose required experience is greater than `profile years + experience_tolerance_years` fails the filter, with a reason containing `N+`. With 0.8 years and tolerance 2.0, "2+ years" passes and "3+ years" fails. A passing result still reports `required_experience_years`.
  Verified by: tests/test_filters.py::test_rejects_too_much_experience, tests/test_filters.py::test_tolerance_boundary, tests/test_filters.py::test_passes_entry_level_job
- **AC-3** When profile experience is below `senior_title_min_experience` (4.0), a title containing any senior keyword as a whole word (Senior, Sr., Lead, Architect, Manager, …) fails. Keywords inside other words ("Staffing") do not. With 6 years of experience, senior titles pass.
  Verified by: tests/test_filters.py::test_rejects_senior_titles, tests/test_filters.py::test_senior_word_inside_other_word_is_ok, tests/test_filters.py::test_senior_titles_allowed_for_experienced_profile
- **AC-4** A company containing a blacklisted company name (case-insensitive substring) fails. A title or description containing a blacklisted keyword (whole word) fails.
  Verified by: tests/test_filters.py::test_blacklists
- **AC-5** Filters are checked in the order company blacklist, keyword blacklist, senior title, required experience, and the first failure's reason is returned.
  Gap: no automated test
- **AC-6** When a filter fails, `Matcher.decide` returns `decision=skip, stage=filter` with the filter reason and `required_experience_years`, **without calling the LLM**, and appends the decision to `decisions.jsonl`.
  Verified by: jobbot eval fixture 03 (6+ years) and fixture 09 ("Lead" title): the `by` column shows `filter`. Gap: no unit test of `Matcher` with a fake client.

**Company type**

- **AC-7** `normalize_company` lowercases, removes corporate/geographic suffixes and punctuation (e.g. "Accenture Solutions Pvt Ltd" gives "accenture").
  Verified by: tests/test_company_type.py::test_normalize
- **AC-8** `in_mnc_list` matches equal names or a whole-word prefix ("Infosys BPM" matches "Infosys"; "TCSX Labs" does not match "TCS"; "Sapient" does not match "SAP"). An empty company never matches.
  Verified by: tests/test_company_type.py::test_in_mnc_list
- **AC-9** `parse_company_size` returns the first integer as a lower bound ("10,000+ employees" gives 10000, "51-200" gives 51), or `None` for missing or non-numeric text.
  Verified by: tests/test_company_type.py::test_parse_company_size
- **AC-10** `resolve_company_type` returns `mnc_list` before `company_size` (an MNC-listed company with "11-50" is still `mnc`). Size `>= mnc_min_employees` gives `mnc`, below gives `startup`. With neither, it returns `("unknown", "unknown")`.
  Verified by: tests/test_company_type.py::test_resolve_order
- **AC-11** When company type is known from data, the final `Decision.company_type` and `company_type_source` are the data values, whatever the LLM returned. When unknown, the LLM's value is used with source `llm`, or `unknown`/`unknown` if the LLM said `unknown`.
  Gap: no automated test (fixtures 02/07 exercise the `mnc_list` path and fixtures 01/05 the `company_size` path, but `eval` does not check `company_type`)
- **AC-12** `load_mnc_list` ignores blank lines and `#` comments and returns `[]` when the file is missing.
  Gap: no automated test

**Resume library and profiles**

- **AC-13** `load_library` raises `ConfigError` when `resumes.yaml` is missing, invalid against the schema, has duplicate ids, references a missing file, or uses a role not defined in `role_tracks`. All problems are reported together.
  Gap: no automated test
- **AC-14** The LLM decision schema's `role_track` enum is exactly the `role_tracks` keys plus `none`, and the `resume_id` enum is exactly the resume ids (in file order) plus `none`. Adding a resume or track to `resumes.yaml` needs no code change.
  Verified by: tests/test_select_resume.py::test_schema_constrains_enums
- **AC-15** `extract_text` reads `.pdf` (PyMuPDF), `.docx` (python-docx paragraphs), `.txt`/`.md` (UTF-8) and returns whitespace-normalized text. Any other extension raises `ValueError`.
  Gap: no automated test
- **AC-16** `build_profiles` reuses a cached profile when the file's sha256, `resume_profile_v1` and the model name all match. Otherwise, or with `force=True`, it re-profiles. It deletes cache entries for ids no longer in the library and writes `data/resume_profiles.json` only when something changed.
  Gap: no automated test
- **AC-17** `jobbot resumes show` prints cached profiles without calling the LLM, marks un-indexed resumes as "not indexed", and fails with "No cached profiles. Run `jobbot resumes index` first." when the cache is empty.
  Gap: no automated test
- **AC-18** Constructing a `Matcher` when any library resume has no profile raises `ValueError` naming the missing ids.
  Gap: no automated test

**LLM decision and post-checks**

- **AC-19** The decide prompt carries the candidate's experience, location, remote and relocate preferences from `profile.yaml`, and for each resume only id, tracks, company type, headline, core skills, domains (if any) and notes (if any). It never includes the resume profile's `total_experience_years`/`seniority` or the full resume text.
  Gap: no automated test
- **AC-20** A description longer than `max_jd_chars` is truncated for the LLM only, and the note `JD truncated to N chars for the LLM` is added.
  Gap: no automated test
- **AC-21** An LLM `apply` with `score < min_score_to_apply` becomes `skip`, with the note `LLM said apply but score S < T`.
  Gap: no automated test
- **AC-22** An LLM `apply` with `role_track = none` becomes `skip`, with a note.
  Gap: no automated test
- **AC-23** On apply, the resume is chosen per BR-5. The LLM's choice is kept when it is the exact company-type variant, or an `any` variant when no exact one exists, or any role match when no exact/any variant exists. Otherwise the first preferred resume is used with a "Resume changed from …" note. For a track with no resumes, a valid LLM choice is kept, and `none` gives no resume.
  Verified by: tests/test_select_resume.py::test_keeps_llm_choice_when_it_fits, ::test_overrides_wrong_company_variant, ::test_any_variant_used_when_no_exact, ::test_falls_back_to_other_variant_when_only_one_exists, ::test_unknown_company_type_keeps_any_role_match, ::test_unknown_track_keeps_valid_llm_choice
- **AC-24** If resume selection yields no resume, the decision becomes `skip` with the note `No resume matches this role track`. Every final `skip` has `resume_id = None`. An LLM `role_track` of `none` is stored as `None`.
  Gap: no automated test
- **AC-25** An LLM-stage `Decision` records `model`, `prompt_version = "decide_v1"`, `latency_s`, `score`, `role_track`, `company_type`, `company_type_source` and `required_experience_years`.
  Gap: no automated test (visible in `jobbot eval -v` output)
- **AC-26** Every successful `Matcher.decide` call appends exactly one JSON line to `data/decisions.jsonl` with `ts`, the job's title/company/location/url/platform/description_sha256, and the full `Decision`. The `data/` directory is created if missing.
  Gap: no automated test

**LLM client**

- **AC-27** If the model's content fails pydantic validation, the client retries once with temperature at least 0.3. If the second answer is also invalid, it raises `LLMError`. A valid answer returns the parsed model plus `LLMCallInfo` (model, latency, attempts, token counts).
  Gap: no automated test
- **AC-28** A connection failure or a non-200 HTTP status raises `LLMUnavailable`. A request timeout raises a plain `LLMError`.
  Gap: no automated test of the client. The consumer side (stop on `LLMUnavailable`, mark `failed` on `LLMError`) is verified by tests/test_db_pipeline.py::test_decide_pending_aborts_when_llm_unavailable and ::test_decide_pending_sets_statuses (Step 2).
- **AC-29** An HTTP 400 whose body mentions "thinking", when `think` was sent, is retried once without the `think` option.
  Gap: no automated test
- **AC-30** `jobbot --model X <cmd>` makes that command use model `X` instead of `llm.model`.
  Gap: no automated test

**CLI and evaluation**

- **AC-31** `jobbot match FILE` decides one job. A `.yaml`/`.yml` file is read as `Job` fields (an `expected` block is ignored); any other file is read as the description. `--title/--company/--location/--company-size` override the file's values. The decision panel shows verdict, resume, score, role, company type and source, stage, reason, required experience, notes, and model/prompt version/latency. `ConfigError`, `LLMError` and `ValueError` during matching print `Error: …` and exit 1.
  Gap: no automated test
- **AC-32** `jobbot eval [DIR]` (default `tests/fixtures/jds`) runs every `*.y*ml` file in sorted order. A JD counts as correct when `decision` equals `expected.decision` (if given) **and** `resume_id` equals `expected.resume_id` (if given). It prints a table (JD, expected, got, score, by, secs, ok) and `N/M correct | X.Xs avg per LLM call`. Any `LLMError` aborts the whole eval.
  Gap: no automated test (eval is a manual harness)
- **AC-33** Off-track roles are skipped by the LLM stage: data scientist (04), React frontend (05), Android (08).
  Verified by: jobbot eval fixtures 04, 05, 08 (LLM-dependent; not run in this documentation pass)
- **AC-34** Entry-level on-track jobs are applied to with the expected resume: junior DevOps at a startup (01) and AWS cloud at an MNC (07) get the devops resume; Java at an MNC (02), SDE-I (06) and Python/Go backend (10) get the software-dev resume.
  Verified by: jobbot eval fixtures 01, 02, 06, 07, 10 (LLM-dependent, and expected ids depend on the private library; see OQ-6)
- **AC-35** Over-experienced and senior-title jobs are skipped at the filter stage: SRE requiring 6+ years (03) and "Lead Backend Engineer" (09).
  Verified by: jobbot eval fixtures 03, 09 (deterministic given a profile with under 4 years of experience)

---

## 12. Open questions & assumptions

These are recorded as found and have **not** been fixed in code.

- **OQ-1 Filters listed in CLAUDE.md that are not implemented.** CLAUDE.md's Filter step lists "already applied" and "wrong location". `filters.py` implements neither: `profile.preferred_locations` is loaded but never used, and the job location only reaches the LLM prompt. Assumption: "already applied" belongs to the job store (Step 2, dedup by job key), and location is left to the LLM. Confirm.
- **OQ-2 Company-size step not fed in practice.** CLAUDE.md says company size comes "from Indeed's company page", but nothing in `platforms/indeed/` sets `Job.company_size`. Only `jobbot match --company-size` or fixture files supply it. For scanned jobs, resolution effectively goes MNC list → LLM.
- **OQ-3 Timeouts are per-job failures.** `httpx.TimeoutException` raises plain `LLMError`, not `LLMUnavailable`. If the model is too slow for `timeout_s` (600 s), every job waits 10 minutes and is marked `failed` instead of the run stopping. Is that intended?
- **OQ-4 Enums only enforced by Ollama's grammar.** `LLMDecision.role_track`/`resume_id` are `str` in pydantic, so a model or server that ignores `format` could return an out-of-enum track. Combined with BR-5 step 2 (a track with no candidates keeps any valid LLM resume), a job in a track with no resume, or in an unknown track, can still end as `apply`. This behaviour is pinned by `test_unknown_track_keeps_valid_llm_choice`. Is it desired, or should an unknown or empty track force skip?
- **OQ-5 `none` is not reserved.** Nothing stops a resume id or role track named `none`, which would collide with the sentinel value.
- **OQ-6 Eval fixtures are tied to the private library.** The fixtures expect resume ids `software_dev` / `devops_cloud` (the user's current library), while `resumes.example.yaml` uses `sde_startup` / `sde_mnc`. Fixtures 03/09 also assume profile experience below 4 years. `jobbot eval` results therefore depend on gitignored personal config and aren't reproducible from the repo alone.
- **OQ-7 "Inputs hash" logging is partial.** CLAUDE.md asks to log "inputs hash, output, latency". Only `description_sha256` is logged. There is no hash of the full prompt (profile facts, resume summaries, settings), and `LLMCallInfo.attempts` and the token counts are dropped. Failed calls (`LLMError`) are not logged at all. Filter-stage decisions record no settings snapshot.
- **OQ-8 Single-slot profile cache per resume.** The cache key includes the model, but there is one entry per resume id. `jobbot --model llama3.2 eval` re-profiles every resume with llama3.2 and **overwrites** the gpt-oss profiles, and switching back re-profiles again. `match`, `eval` and `decide` re-profile silently via `_build_matcher` (`cli.py:119`), possibly with a model known to produce wrong profiles. `resumes show` displays cached profiles without checking freshness.
- **OQ-9 Partial profiling progress is lost.** `build_profiles` writes the cache only at the end, so an `LLMError` on resume N discards the profiles already built in that run.
- **OQ-10 Experience regex false positives.** The `exp` context check also matches "expanding", "expertise", "expected", "export", so non-experience durations near such words (e.g. "a 2 years contract … expected") may be counted. Only the description is scanned, so a title like "SDE (5+ yrs)" is ignored.
- **OQ-11 Blacklist semantics differ.** `blacklist_companies` uses a plain substring match: a short entry such as "EY" also matches "Keyence". The MNC list uses whole-word prefix matching. Should they be consistent?
- **OQ-12 Uncaught errors give tracebacks.** In `match`, `_load_job_file` runs outside the `try` (`cli.py:166`), so a bad YAML or JD gives a traceback. `resumes index` doesn't catch `ValueError` (unsupported format) or a corrupt `resume_profiles.json` (`JSONDecodeError`). A pydantic `ValidationError` in `settings.yaml` isn't wrapped in `ConfigError`. An image-only PDF yields empty text that is still sent for profiling.
- **OQ-13 Unescaped Rich markup.** `match` and `eval` print LLM reasons and JD titles without `rich.markup.escape`, unlike the Step 2 `decide` output, so text with `[...]` may render wrongly. This is cosmetic.
- **OQ-14 Client API.** CLAUDE.md says the client supports "OpenAI-compatible or native API"; only the native `/api/chat` is implemented.
- **OQ-15 Local-only is not enforced.** `llm.base_url` accepts any URL. Pointing it at a remote host would send resume text and JDs off the machine, breaking rule 2 (ADR-0001). Should the code refuse non-loopback hosts?
- **OQ-16 No `@pytest.mark.llm` tests exist.** `pyproject.toml` declares the marker and deselects it by default, but no test uses it. Matcher post-checks (AC-19..AC-26) could be tested with a fake `OllamaClient` without an LLM.
- **OQ-17 An LLM skip is never upgraded.** A high-score `skip` stays `skip`. This is assumed intended (conservative).
- **Assumption A-1.** `profile.yaml`'s `total_experience_years` is the single source of truth for experience (BR-6). This is intentional per CLAUDE.md.
- **Assumption A-2.** Processing is strictly sequential (one LLM call at a time), as required by the 6 GB VRAM environment. The code has no concurrency.

## 13. Dependencies

- **Runtime services:** a local Ollama server at `llm.base_url` with the configured model pulled (default `gpt-oss:20b`; see the risks in `implementation-plan.md`).
- **Python packages** (`pyproject.toml`): `pydantic`, `pyyaml`, `httpx`, `pymupdf`, `python-docx`, `typer`, `rich`. `beautifulsoup4` is only used by `text.html_to_text`, which the Step 2 scanner uses, not the matcher.
- **User-maintained inputs:** `profile.yaml`, `resumes/resumes.yaml` + resume files, optional `config/settings.yaml`, `config/mnc_companies.txt`.
- **Other capabilities:** none upstream. Downstream: Step 2 (Indeed scanner + job store: `pipeline.decide_pending`, `db.status_for`) consumes `Matcher.decide` and the `Decision` model. Steps 3–4 will consume `Decision.resume_id` / `notes`.
- **ADRs:** ADR-0001-local-only-llm (`documentation/development/decisions/`).
