# Coding standard

## Language and layout
- **Python 3.13** (`requires-python = ">=3.13"`), `src/` layout, one package: `src/jobbot`.
- Type hints on every function signature and public attribute. `from __future__ import annotations` at the top of modules.
- Use `pathlib.Path` for every path. The project runs on Windows; no POSIX-only assumptions (no hard-coded `/`, no shell-specific behaviour).
- New dependencies go in `pyproject.toml` and need a reason (see the workflow, section 10).

## Models and validation
- `pydantic` v2 for config (`config.py`), shared models (`models.py`) and every LLM output model.
- Validate at the edges: config files when loaded, LLM output when returned, scraped data when parsed.
- Raise clear errors (`ConfigError`, `LLMError`, `LLMUnavailable`, `BrowserError`). Don't swallow exceptions silently.

## Lint and format
- `ruff` (config in `pyproject.toml`): line length 100, target `py313`, rules `E, F, I, UP, B`.
- Before finishing any change:
  ```powershell
  .venv\Scripts\ruff check src tests
  .venv\Scripts\ruff format src tests
  ```

## Where things live

| Thing | The only place for it |
|---|---|
| Prompt templates | `src/jobbot/llm/prompts.py` |
| Prompt versions | Constants next to the prompt, e.g. `DECIDE_PROMPT_VERSION = "decide_v1"`. Bump the version whenever the prompt text or its schema changes, and store it with each result (`Decision.prompt_version`, the profile cache) |
| Indeed selectors, page markers, URL patterns | `src/jobbot/platforms/indeed/parse.py` |
| Platform code | `src/jobbot/platforms/<name>/` |
| Schema | `src/jobbot/migrations/NNNN_name.sql` (never `CREATE`/`ALTER` in Python) |
| Settings and their defaults | `config.py` models, documented in `config/settings.example.yaml` |
| Shared data models | `src/jobbot/models.py` |

## Boundaries
- Platform-specific code must not leak into `matcher/` or `llm/`. Those work on `Job` and `Decision` only.
- `parse.py` is pure (HTML/JSON in, data out, no browser). Browser actions live in `scanner.py` / `applier.py` and `browser.py`.
- `pipeline.py` glues the store and the matcher; keep business rules in `matcher/`.
- Adding a resume or role track must never need a code change (`resumes/resumes.yaml` drives it).

## LLM calls
- Only through `OllamaClient.chat_json` with a JSON schema and a pydantic output model.
- Retry once on invalid output, then fail (`LLMError`). Never guess or patch up a bad answer.
- One call at a time; no parallel LLM calls.
- Keep prompts short: resume summaries, not full text; truncate JDs to `llm.max_jd_chars`.
- Keep the model name in config (`llm.model`), never hard-coded in logic.

## SQL
- `sqlite3` with `?` parameters for every value. Never format scraped, user or LLM text into SQL.
- Status changes go through `JobStore` methods, not ad-hoc `UPDATE`s elsewhere.

## Browser code
- Headed Chrome only (`headless=False`), persistent profile, `channel="chrome"`.
- Use `human_pause` between actions and `wait_for_human` for challenges and sign-in.
- When a page doesn't match the expected selectors, fail loudly and save a screenshot to `data/screenshots/`.

## Style
- Small, focused functions. Docstrings on public functions explain *why*, not just *what*.
- Comments for non-obvious decisions (e.g. field order in `LLMDecision`).
- No speculative abstractions; follow the existing patterns.
