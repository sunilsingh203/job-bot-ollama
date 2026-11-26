# Testing standard

## Tools
- `pytest` (config in `pyproject.toml`): `testpaths = ["tests"]`, `addopts = "-m 'not llm'"`.
- Tests that call the local Ollama model are marked `@pytest.mark.llm` and are **skipped by default**.
- `jobbot eval` measures decision accuracy on the sample JDs.

## Commands (Windows, from the repo root)

```powershell
.venv\Scripts\python -m pytest                 # unit tests, no LLM
.venv\Scripts\python -m pytest -m llm          # LLM tests (needs Ollama running and the model loaded)
.venv\Scripts\python -m pytest tests\test_filters.py -q
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
.venv\Scripts\jobbot eval -v                   # decision accuracy on tests/fixtures/jds/
.venv\Scripts\jobbot --model llama3.2 eval     # same, with a faster model (plumbing only)
```

In Git Bash, set `PYTHONIOENCODING=utf-8` when piping output.

## What to test

| Kind | How |
|---|---|
| Normal behaviour | Unit tests per module (`test_filters.py`, `test_company_type.py`, `test_select_resume.py`, ...) |
| Validation failures | Bad config, bad `resumes.yaml`, LLM output that fails the schema (use a fake client) |
| State transitions | `JobStore` status changes, `decide_pending` with fake matchers raising `LLMError` / `LLMUnavailable` (`test_db_pipeline.py`) |
| Migrations | A fresh DB gets the latest `user_version`; an older DB is upgraded; applying twice is a no-op |
| Parsing | Saved pages in `tests/fixtures/indeed/`, never the live site (`test_indeed_parse.py`) |
| Decision quality | `tests/fixtures/jds/*.yaml` with an `expected:` block, run by `jobbot eval` |
| Safety rules | e.g. the browser is launched headed; the filler never clicks Submit; LLM-written answers are flagged |
| Regressions | Add a test for every bug fixed |

## Fixtures
- `tests/fixtures/jds/NN_short_name.yaml`: a sample JD (`title`, `company`, `location`,
  `company_size`, `description`) with an `expected:` block. Add one when a real job was decided
  wrongly.
- `tests/fixtures/indeed/`: trimmed **real** Indeed pages. Scrub personal data before saving.
- Use `tmp_path` for databases and data dirs. Tests never touch the real `data/`, `resumes/`
  or `profile.yaml`.
- No test opens a browser or calls the internet.

## Prompt and matching changes
Any change to `llm/prompts.py`, the decision schema, `matcher/` or the matching settings:
1. Bump the prompt version if the prompt or schema changed.
2. Run `jobbot eval -v` before and after, with the same model, and record both scores in the
   plan or review.
3. Look at `data/decisions.jsonl` for latency changes.

## Honesty rule
Test what you ran, and **never claim a result you didn't run.** In plans and reviews, paste the
exact command and its summary line. If something couldn't be run (e.g. Ollama out of memory, no
`-m llm` run), say so explicitly and mark the related AC "not verified".
