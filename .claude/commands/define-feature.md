---
description: Draft a feature specification (Lane A) or change definition (Lane B) for a jobbot capability
argument-hint: <capability> | <capability>/changes/<change>
---

# Define feature: $ARGUMENTS

You are drafting the specification for `$ARGUMENTS` following the spec-driven workflow.

Target folder: `documentation/development/features/$ARGUMENTS/`
- If `$ARGUMENTS` has the form `<capability>/changes/<change>`, this is **Lane B**: write
  `change-definition.md` from `documentation/development/templates/change-definition.md`.
- Otherwise this is **Lane A**: write `specification.md` from
  `documentation/development/templates/specification.md`.

If `$ARGUMENTS` is empty, ask which capability to define and stop.

## 1. Read first
- `CLAUDE.md` (non-negotiable rules, decisions, pipeline, layout)
- `documentation/development/AI-DEVELOPMENT-WORKFLOW.md` (sections 3, 4, 5, 8)
- `documentation/customer/` (the developer's goals, platform notes, Indeed observations)
- `documentation/development/architecture/overview.md`, `security.md`, `data.md`
- `documentation/development/decisions/README.md` and any ADR that applies
- `.claude/rules/*.md`
- Existing specs of related capabilities in `documentation/development/features/`
- For Lane B: the capability's current `specification.md` and `changelog.md`
- For Lane B: `request.md` in the change folder, if present (the developer's what/why/done-when;
  treat its open questions as questions to resolve, not as decided rules)

## 2. Inspect the code
Look at what already exists in `src/jobbot/` and `tests/` for this capability (modules, CLI
commands in `cli.py`, DB columns and statuses in `db.py` and `src/jobbot/migrations/`, config
keys in `config.py`). Describe current behaviour from the code, not from memory.

## 3. State assumptions and ask
List what you understood, your assumptions, and the open questions. **Ask the developer about
anything that is a business rule.** Don't invent rules (e.g. thresholds, which jobs qualify,
what the dashboard shows). If answers are needed before a useful draft, ask and stop.

## 4. Draft
Write the spec with every template section: purpose, actors, scope / out of scope, business rules
(BR-n), data entities, states and transitions, permissions and safety (what the bot does alone
vs. what needs the human), validation, error cases, numbered testable acceptance criteria (AC-n,
each saying how it's verified), open questions and assumptions, dependencies.
- Check every rule against the safety rules in `.claude/rules/safety.md`. Flag conflicts.
- If the work would change the DB, prompts, safety rules or Indeed integration, say so.
- Don't touch source code. Don't create `implementation-plan.md` or `plan-approval.md`.

## 5. Report
End with a short report:
- File written (path) and the lane
- Number of ACs; open questions that block planning
- Next step: the developer reviews/edits the spec, then `/plan-feature $ARGUMENTS`
