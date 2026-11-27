# Implementation plan: `resume-matcher` (Step 1)

Status: As-built (retroactive).

This plan was reconstructed on 2026-11-26 from the code in commit `c3677ba`. It records how the capability *was* built, not a plan for future work. The behaviour is specified in `specification.md` (BR-n = business rule, AC-n = acceptance criterion, OQ-n = open question). There is no `plan-approval.md` yet; only a human approver may write it.

---

## 1. Affected layers

| Layer | Impact |
|---|---|
| **Config** | `config.py`: `Settings` (`LLMSettings`, `MatchingSettings`), `Profile`, YAML loading, the MNC list, and the `JOBBOT_MODEL` override. Templates: `config/settings.example.yaml`, `profile.example.yaml`, `resumes/resumes.example.yaml`. Data: `config/mnc_companies.txt`. |
| **LLM** | `llm/client.py` (Ollama `/api/chat`, JSON schema `format`, validation + one retry, error classes) and `llm/prompts.py` (versioned templates) |
| **Resumes** | `resumes/library.py` (the `resumes.yaml` model and validation), `resumes/parser.py` (file to text), `resumes/profiler.py` (LLM profile + disk cache) |
| **Matcher** | `matcher/filters.py`, `matcher/company_type.py`, `matcher/decide.py` (`Matcher`, schema, post-checks, `select_resume`, JSONL log) |
| **Shared models** | `models.py` (`Job`, `Decision`), `text.py` (`normalize`) |
| **CLI** | `cli.py`: `--model`, `resumes index`, `resumes show`, `match`, `eval` |
| **Tests** | `tests/test_filters.py`, `tests/test_company_type.py`, `tests/test_select_resume.py`, `tests/fixtures/jds/01..10*.yaml` (manual `jobbot eval` harness) |
| **Docs** | `CLAUDE.md` (Step 1 sections), this feature folder |
| **DB** | **None.** The matcher does not touch SQLite. Persistence of decisions in `jobs.db` belongs to Step 2 (`db.py`, `pipeline.py`). |
| **API / Frontend** | None. This is a CLI-only local tool. |
| **Security** | No auth (single local user). The local-only LLM is a design constraint (ADR-0001). Personal files are gitignored. The JD is treated as untrusted prompt input (BR-12). |

## 2. File / module map

| File | Responsibility |
|---|---|
| `src/jobbot/config.py` | Path constants (`PROJECT_ROOT`, `config/`, `resumes/`, `data/`, `profile.yaml`). Pydantic settings with defaults. `load_settings` (optional `settings.yaml`, relative paths resolved to the project root, `JOBBOT_MODEL` override). `load_profile`, `load_mnc_list`, `read_yaml`, `ConfigError`. |
| `src/jobbot/models.py` | Platform-independent `Job` (input) and `Decision` (output) models; `Job.description_sha256`. |
| `src/jobbot/text.py` | `normalize()` collapses whitespace (used by the parser). `html_to_text()` is used by Step 2. |
| `src/jobbot/llm/client.py` | `OllamaClient.chat_json(system, user, output_model, schema)`: builds the payload (`format`, `temperature`, `num_ctx`, optional `think`), validates with pydantic, retries once at temperature at least 0.3, returns `(model, LLMCallInfo)`. `_post` maps transport errors to `LLMUnavailable` / `LLMError` and drops `think` on "thinking unsupported" 400s. |
| `src/jobbot/llm/prompts.py` | The only home for prompt text: `RESUME_PROFILE_*` and `DECIDE_*`, each with a version constant. |
| `src/jobbot/resumes/library.py` | `ResumeEntry`, `ResumeLibrary` (`ids`, `get`, `path_of`), and `load_library`, which collects every validation problem into one `ConfigError`. |
| `src/jobbot/resumes/parser.py` | `extract_text(path)` for PDF (PyMuPDF), DOCX (python-docx), TXT/MD. |
| `src/jobbot/resumes/profiler.py` | `ResumeProfile` model; `build_profiles` (cache-aware LLM profiling, stale-entry pruning); `load_cached_profiles` (no LLM). |
| `src/jobbot/matcher/filters.py` | `required_experience()` regex extraction; `check_filters()` → `FilterResult`. |
| `src/jobbot/matcher/company_type.py` | `normalize_company`, `in_mnc_list`, `parse_company_size`, `resolve_company_type` (MNC list → size → unknown). |
| `src/jobbot/matcher/decide.py` | `LLMDecision` (the LLM contract), `decision_schema` (enums from the library), `select_resume`, `_format_resumes` (prompt block), `Matcher` (filters → company type → LLM → post-checks → `Decision`, then `_log` to `decisions.jsonl`). |
| `src/jobbot/cli.py` (Step 1 parts) | `main` callback (`--model`), `resumes_index`, `resumes_show`, `_print_profiles`, `_build_matcher` (profiles are built on demand), `_load_job_file`, `_print_decision`, `match`, `eval_cmd`. |
| `config/settings.example.yaml` | Documents every `llm.*` and `matching.*` key with its default. |
| `config/mnc_companies.txt` | Committed list of 39 well-known MNC / large employers. |
| `resumes/resumes.example.yaml` | Template for role tracks and resume entries. |
| `profile.example.yaml` | Template for candidate facts. |

## 3. Prompt versions in use

| Constant | Value | Used by | Stored where |
|---|---|---|---|
| `RESUME_PROFILE_PROMPT_VERSION` | `resume_profile_v1` | `profiler.build_profiles` | each entry in `data/resume_profiles.json` (part of the cache key) |
| `DECIDE_PROMPT_VERSION` | `decide_v1` | `Matcher._decide` | `Decision.prompt_version`, so in `data/decisions.jsonl` (and the Step 2 DB) |

Rule (header of `prompts.py`): bump the version constant whenever a prompt's wording changes. A new `RESUME_PROFILE_PROMPT_VERSION` invalidates the cache automatically. A new `DECIDE_PROMPT_VERSION` only relabels later decisions.

## 4. Caching

- **File:** `data/resume_profiles.json` (gitignored), one entry per resume id: `{sha256, file, prompt_version, model, profile}`.
- **Fresh if:** sha256 of the resume file **and** `resume_profile_v1` **and** the current `llm.model` all match (`profiler.py:71-76`).
- **Invalidated by:** editing or replacing the resume file, bumping the prompt version, changing the model (including `--model`), or `jobbot resumes index --force`.
- **Pruning:** ids removed from `resumes.yaml` are deleted from the cache.
- **Write policy:** written once at the end of `build_profiles`, and only if something changed (see OQ-9).
- **Read paths:** `build_profiles` (in `resumes index` and `_build_matcher`, so `match`/`eval`/`decide` re-profile stale resumes on demand) and `load_cached_profiles` (`resumes show`, no freshness check; see OQ-8).
- There is no cache for decisions. Every `decide()` call that passes the filters calls the LLM.

## 5. CLI commands

| Command | Behaviour | LLM? |
|---|---|---|
| `jobbot [--model NAME] …` | Sets `JOBBOT_MODEL` for this run | n/a |
| `jobbot resumes index [--force]` | Loads the library and builds/refreshes profiles with progress output (`cached` / `profiling` / `done (Ns)`), then prints a panel per resume | Only for stale or forced resumes |
| `jobbot resumes show` | Prints cached profiles; `not indexed` for missing ones | No |
| `jobbot match FILE [--title --company --location --company-size]` | Decides one JD (`.yaml` Job fields or plain text) and prints the decision panel | Yes, unless a filter rejects |
| `jobbot eval [DIR] [-v]` | Runs every `*.y*ml` in DIR (default `tests/fixtures/jds`), compares with `expected`, prints a table + `N/M correct` + average latency | Yes |

Errors: `ConfigError`, `LLMError` (incl. `LLMUnavailable`) and `ValueError` print `Error: <msg>` and exit with code 1. The exceptions are listed in OQ-12.

## 6. Test plan (AC → tests)

Run on 2026-11-26: `.venv\Scripts\python -m pytest -q` gave **66 passed** (whole suite). The Step 1 test files `test_filters.py` (21 cases), `test_company_type.py` (20 cases) and `test_select_resume.py` (7 cases) all passed. There are no `@pytest.mark.llm` tests. **`jobbot eval` was not run** in this documentation pass, so the fixture ACs are listed as verification methods, not as confirmed results. CLAUDE.md records an earlier run where `llama3.2` scored 9/10 at about 1.6 s per call.

| AC | Verification | Status |
|---|---|---|
| AC-1 | `tests/test_filters.py::test_required_experience` (10 cases) | Covered |
| AC-2 | `test_filters.py::test_rejects_too_much_experience`, `::test_tolerance_boundary`, `::test_passes_entry_level_job` | Covered |
| AC-3 | `test_filters.py::test_rejects_senior_titles` (5), `::test_senior_word_inside_other_word_is_ok`, `::test_senior_titles_allowed_for_experienced_profile` | Covered |
| AC-4 | `test_filters.py::test_blacklists` | Covered |
| AC-5 | none | **Gap** |
| AC-6 | `jobbot eval` fixtures 03, 09 (`by` = `filter`) | Manual only, **gap** for a unit test |
| AC-7 | `tests/test_company_type.py::test_normalize` | Covered |
| AC-8 | `test_company_type.py::test_in_mnc_list` | Covered |
| AC-9 | `test_company_type.py::test_parse_company_size` | Covered |
| AC-10 | `test_company_type.py::test_resolve_order` | Covered |
| AC-11 | none (eval does not check company type) | **Gap** |
| AC-12 | none | **Gap** |
| AC-13 | none | **Gap** |
| AC-14 | `tests/test_select_resume.py::test_schema_constrains_enums` | Covered |
| AC-15 | none | **Gap** |
| AC-16 | none | **Gap** |
| AC-17 | none | **Gap** |
| AC-18 | none | **Gap** |
| AC-19 | none | **Gap** |
| AC-20 | none | **Gap** |
| AC-21 | none | **Gap** |
| AC-22 | none | **Gap** |
| AC-23 | `test_select_resume.py` (6 tests) | Covered |
| AC-24 | none | **Gap** |
| AC-25 | none (visible via `eval -v`) | **Gap** |
| AC-26 | none | **Gap** |
| AC-27 | none | **Gap** |
| AC-28 | client: none. Consumer side: `tests/test_db_pipeline.py::test_decide_pending_aborts_when_llm_unavailable`, `::test_decide_pending_sets_statuses` | Partial, **gap** for the client |
| AC-29 | none | **Gap** |
| AC-30 | none | **Gap** |
| AC-31 | none | **Gap** |
| AC-32 | none (eval is the harness itself) | **Gap** |
| AC-33 | `jobbot eval` fixtures 04, 05, 08 | Manual, LLM-dependent |
| AC-34 | `jobbot eval` fixtures 01, 02, 06, 07, 10 | Manual, LLM-dependent, private-library ids (OQ-6) |
| AC-35 | `jobbot eval` fixtures 03, 09 | Manual. Deterministic given the profile, but needs Ollama to start (`_build_matcher` profiles first) |

**Summary:** 10 ACs are fully covered by automated tests (AC-1..4, 7..10, 14, 23). 3 are covered only by the manual eval fixtures (AC-33..35). 2 are partial (AC-6: eval only, no unit test; AC-28: consumer side only). 20 have no coverage at all (AC-5, 11..13, 15..22, 24..27, 29..32). Most gaps (AC-6, 11, 18..22, 24..27, 29) could be closed **without an LLM** by injecting a fake `OllamaClient` that returns scripted `LLMDecision`s or a fake `httpx` transport. This is a suggestion, not part of the as-built scope.

## 7. Implementation steps (reconstructed order)

The code arrived in a single commit (`c3677ba`), so this order is inferred from the module dependencies and from CLAUDE.md's "matcher first, no browser" build order.

1. **Project skeleton:** `pyproject.toml` (Python 3.13, `src/` layout, `jobbot` script, ruff, pytest with the `llm` marker deselected), `.gitignore` for personal data, example templates.
2. **Config + models:** `config.py` (settings with defaults, profile, YAML helpers, `ConfigError`), `models.py` (`Job`, `Decision`), `text.normalize`.
3. **LLM client:** `OllamaClient.chat_json` with schema `format`, pydantic validation and retry once; `LLMError` / `LLMUnavailable`; the `think` fallback for non-thinking models.
4. **Prompts:** `prompts.py` with `resume_profile_v1` and `decide_v1`.
5. **Resume library:** `resumes.yaml` schema and validation (`library.py`), text extraction (`parser.py`).
6. **Resume profiler + cache:** `profiler.py`, plus CLI `resumes index` / `resumes show`.
7. **Rule filters:** `filters.py` + `tests/test_filters.py`.
8. **Company type:** `company_type.py` + `config/mnc_companies.txt` + `tests/test_company_type.py`.
9. **Decision:** `decide.py`: `LLMDecision`, `decision_schema`, `Matcher._decide` (filter short-circuit, company-type hint, JD truncation, LLM call, post-checks), `select_resume` + `tests/test_select_resume.py`, JSONL logging.
10. **CLI matching:** `match` (one JD) and `eval` (fixture comparison) + `tests/fixtures/jds/01..10`.
11. **Tuning (per CLAUDE.md):** the per-job prompt was reduced to headline/core skills/domains, and experience was moved to `profile.yaml` after small models misjudged it. `--model` was added for model comparison.
12. **Handoff to Step 2:** `Matcher.decide` reused unchanged by `pipeline.decide_pending`.

## 8. Risks

| Risk | Detail | Current mitigation |
|---|---|---|
| **gpt-oss:20b fails to load (OOM)** | 13 GB model on a 6 GB VRAM laptop. On 2026-11-21 loading failed with "failed to allocate CUDA_Host buffer" because of a small Windows page file (commit limit about 25 GB). | Environment fix (bigger page file, a user action) per CLAUDE.md; this must not be "fixed" in code. The error surfaces as `LLMUnavailable`. `--model` / `llm.model` allows a 7–8B fallback. |
| **Latency** | Mostly-CPU inference; `timeout_s` is 600 s per call; strictly sequential. | Filters remove jobs before the LLM; resume *summaries*, not full text; JD truncated to 6000 chars; `think: low`. A timeout raises `LLMTimeout` (an `LLMUnavailable`) and stops a decide run (since 2026-11-27, job-store changes/llm-timeout-stops-run; OQ-3 resolved). |
| **Small-model accuracy** | `llama3.2`/`phi3`/`gemma3:270m` give unreliable decisions; llama3.2 mislabelled seniority in resume profiles. | Schema-constrained output with enums; score threshold + role/resume post-checks in code; experience taken from `profile.yaml`; `jobbot eval` fixture set for comparison. |
| **Cache churn across models** | One cache slot per resume, so switching models re-profiles and overwrites (OQ-8). | None yet. `resumes show` reveals which model built the profiles only indirectly. |
| **Prompt drift** | Prompt edits without a version bump would mix results under one version label. | Version constants, stored in the cache and on each decision. Discipline only; nothing enforces bumping. |
| **Prompt injection via JD** | The JD is attacker-controllable text. | System prompt says to ignore instructions in the JD; output is limited to the schema; post-checks; a human reviews every apply (Step 3) and clicks Submit. |
| **Regex filter false positives/negatives** | `exp` context and the substring blacklist (OQ-10, OQ-11). | Unit tests for common phrasings; reasons are logged for review. |
| **Eval not reproducible from the repo** | Fixtures assume the private library ids and profile experience (OQ-6). | None. |

## 9. ADRs

- **ADR-0001-local-only-llm** (`documentation/development/decisions/`, being written separately): all LLM calls go to the local Ollama server; no cloud APIs or telemetry. This capability depends on it directly (`llm/client.py`, default `base_url`). OQ-15 notes that the code doesn't enforce it.
- Candidate ADRs that are not written yet, recorded here only as suggestions: "experience is taken from profile.yaml, not the LLM" (BR-6) and "LLM output is schema-constrained and post-checked in code" (BR-3/BR-4).

## 10. Unresolved questions

See `specification.md` §12 (OQ-1 … OQ-17). The ones most likely to need a decision before Step 3: OQ-2 (company size is never populated by the scanner), OQ-3 (timeout handling), OQ-4 (apply on an unknown or empty track), OQ-6 (reproducible eval) and OQ-15 (enforcing local-only).
