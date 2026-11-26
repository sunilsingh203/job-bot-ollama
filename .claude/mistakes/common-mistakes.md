# Common mistakes (Claude)

Mistakes Claude has made while developing this project, and how to avoid them. This file is
loaded into every session through `CLAUDE.md`. **Before finishing any task, check your work
against the "How to avoid" line of every entry that applies.**

## Rules for this file

- **Add an entry** when:
  - the developer corrects Claude
  - a review finds a defect that Claude introduced
  - Claude catches its own mistake (for example a wrong claim, a skipped check, or a doc/code mismatch)

  Only record mistakes that could happen again. One-off typos don't count.
- **Same mistake again:** don't add a duplicate. Add 1 to `Seen`, update the date and reset `Clean streak` to 0.
- **Clean streak:** at the end of a task where an entry's situation actually came up and Claude
  avoided the mistake, add 1 to its streak. Tasks where the situation never came up don't count.
- **Delete an entry** when either:
  - its clean streak reaches **3/3**, or
  - an automated guard now catches it (a test, a ruff rule, a hook). Name the guard in the task report.

  Git history keeps deleted entries. Say in the task report which entries were deleted and why.
- **Who can change this file:** the developer can add, edit or delete any entry at any time.
  Claude adds entries and updates counts. It deletes an entry only under the rule above.
- **Keep it short:** at most ~15 entries, each 4–6 lines. Merge similar entries.
  Number entries `M-NNN` and never reuse a number.

Entry format:

```
## M-NNN: <short title>
- **Mistake:** what went wrong (concrete).
- **Why it matters:** the effect on the user, the data or the Indeed account.
- **How to avoid:** a concrete rule or check to apply next time.
- **Evidence:** file:line, review or date where it was seen.
- **Seen:** N× (last YYYY-MM-DD) · **Clean streak:** n/3
```

---

## M-001: Docs describe behaviour the code doesn't have
- **Mistake:** CLAUDE.md described several features as built when they weren't:
  - saving a screenshot on failure
  - an OpenAI-compatible client
  - the "already applied" and "wrong location" filters
  - storing the prompt version "in the DB"
- **Why it matters:** the developer and later sessions trust docs that are wrong, and the missing pieces go unnoticed.
- **How to avoid:** write docs from the code as it is, not from the plan. Label anything not built
  yet "(planned)". In a review, check every documented claim against the code with a grep.
- **Evidence:** as-built review, 2026-11-26 (`features/*/specification.md`, Open questions).
- **Seen:** 1× (last 2026-11-26) · **Clean streak:** 0/3

## M-002: Code paths shipped without tests
- **Mistake:** 36 acceptance criteria across the 3 built capabilities have no automated test, for example:
  - the CLI commands and `decide --limit`
  - LLM client retry/timeout
  - `wait_for_human`, pacing and the per-run cap
- **Why it matters:** regressions in the paths that protect the account (pacing, challenge waits) would go unnoticed.
- **How to avoid:** every new branch, CLI flag or error path gets a test in the same change. Use
  a fake LLM client or page object instead of skipping the test. The implementation plan maps each AC to a test.
- **Evidence:** AC tables in `features/{resume-matcher,indeed-scanner,job-store}/specification.md`.
- **Seen:** 1× (last 2026-11-26) · **Clean streak:** 0/3

## M-003: Error type picked without thinking about the effect on the whole run
- **Mistake:** an Ollama timeout raises `LLMError` (per-job), not `LLMUnavailable` (stop the run).
  A stuck model then marks every job `failed`, one by one, after up to 600 s each.
- **Why it matters:** a decide run wastes hours, and every job has to be re-queued.
- **How to avoid:** for each exception, decide whether it should stop the run or skip one item,
  write that choice down in the spec, and test both cases.
- **Evidence:** `src/jobbot/llm/client.py`; resume-matcher OQ-3; job-store Open questions.
- **Seen:** 1× (last 2026-11-26) · **Clean streak:** 0/3

## M-004: Hard-coded numbers and counters that disagree with config or docs
- **Mistake:**
  - the scanner steps result pages by 10, while `searches.yaml` says about 15 jobs per page
  - `max_new_jobs_per_run` is checked against descriptions read, not against new jobs
- **Why it matters:** the pacing and caps that protect the Indeed account don't do what the config says.
- **How to avoid:** read limits from config or a named constant. Make the variable you check
  count exactly what the setting's name says. Add a test that checks the limit.
- **Evidence:** `src/jobbot/platforms/indeed/scanner.py`; indeed-scanner Open questions.
- **Seen:** 1× (last 2026-11-26) · **Clean streak:** 0/3
