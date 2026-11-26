# Specification: <capability>

> Lane A. Path: `documentation/development/features/<capability>/specification.md`.
> Template sections are a starting point; add or remove sections when it fits.

| | |
|---|---|
| Status | Draft / Approved / Built |
| Owner | the developer |
| Last updated | YYYY-MM-DD |
| Related | ADRs, other capabilities, `CLAUDE.md` sections |

## 1. Purpose
What this capability does and why it exists, in a few sentences.

## 2. Actors
Who or what takes part: the user (the developer), the bot (CLI / dashboard), the local LLM,
Indeed (external site), Ollama.

## 3. Scope
### In scope
-
### Out of scope
-

## 4. Business rules
Numbered rules (BR-1, BR-2, ...). Reference `CLAUDE.md` non-negotiable rules where they apply.

## 5. Data entities
Tables/columns, files in `data/`, config keys and models (`models.py`) this capability reads or writes.
Link to `architecture/data.md` instead of repeating it.

## 6. States and transitions
Job statuses (or other states) this capability sets, and which transitions are allowed.

## 7. Permissions and safety
What the bot may do on its own, and what needs the human (approve, solve a challenge, click Submit).
Which `CLAUDE.md` safety rules apply and how they are kept.

## 8. Validation rules
Input checks: config, scraped data, LLM output (schema + pydantic), user input.

## 9. Error cases
| Case | Expected behaviour |
|---|---|
| | |

## 10. Acceptance criteria
Testable and numbered. Say how each one is verified (unit test, fixture, `jobbot eval`, manual run).

- **AC-1:**
- **AC-2:**

## 11. Open questions and assumptions
Never hide these.

| # | Question / assumption | Status |
|---|---|---|
| Q-1 | | open |

## 12. Dependencies
Other capabilities, config files, external systems (Indeed, Ollama).
