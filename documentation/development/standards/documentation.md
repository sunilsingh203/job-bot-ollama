# Documentation standard

## Where each doc lives

| Doc | Path | Owner |
|---|---|---|
| Agent rules (condensed) | `CLAUDE.md` | developer + AI |
| Focused agent rules | `.claude/rules/*.md` | developer + AI |
| Workflow commands | `.claude/commands/*.md` | developer + AI |
| Claude's common mistakes + how to avoid | `.claude/mistakes/common-mistakes.md` | AI (the developer may edit) |
| This workflow | `documentation/development/AI-DEVELOPMENT-WORKFLOW.md` | developer |
| Architecture | `documentation/development/architecture/` (`overview.md`, `security.md`, `data.md`) | AI keeps in sync |
| Feature specs, plans, reviews | `documentation/development/features/<capability>/` | AI drafts, developer approves |
| Material changes | `documentation/development/features/<capability>/changes/<change>/` | AI drafts, developer approves |
| The developer's description of a feature or big change | `features/<capability>/[changes/<change>/]README.md` (template `templates/feature-readme.md`) | **the developer** (the AI may draft it from chat, marked, with their OK) |
| The developer's request for a small change | `changes/<change>/request.md` (template `templates/request.md`) | **the developer** |
| Plan approvals | `.../plan-approval.md` | **the developer** (or the AI recording their explicit chat approval, ADR-0005) |
| Small changes | `documentation/development/changes/<change>/` | developer (request), AI (plan, review) |
| Decisions | `documentation/development/decisions/ADR-NNNN-title.md` | AI drafts, developer accepts |
| Standards | `documentation/development/standards/` | developer + AI |
| Templates | `documentation/development/templates/` | developer + AI |
| The developer's goals, platform notes | `documentation/customer/` | developer |
| User-facing setup and commands | `README.md` (listed in `CLAUDE.md`, not created yet) | AI keeps in sync |

## Keeping docs in sync

Update docs in the same change as the code. When behaviour changes:

| You changed | Update |
|---|---|
| A capability's behaviour or ACs | Its `specification.md` and `changelog.md` |
| DB schema or statuses | `architecture/data.md`, the migration, the spec |
| Files in `data/` or config keys | `architecture/data.md`, `config/settings.example.yaml`, `README.md` |
| Module layout or boundaries | `architecture/overview.md`, the layout in `CLAUDE.md` |
| A safety control | `architecture/security.md`, `.claude/rules/safety.md` (and `CLAUDE.md` only with the developer's OK) |
| CLI commands or flags | `README.md`, the Commands section of `CLAUDE.md` |
| A significant technical choice | A new ADR, and the index in `decisions/README.md` |
| A capability's build status | The capability tables in `architecture/overview.md` and the workflow, section 13 |

If code and docs disagree and it's unclear which is right, ask the developer; don't silently
"fix" either.

## Changelog format

One `changelog.md` per capability, newest first (template: `templates/changelog.md`):

```
| Date | Lane | Change | Link / commit |
|---|---|---|---|
| 2026-11-26 | D | Default scan.delay_max_s raised from 6.0 to 8.0 | abc1234 |
```

- One line per change that affects documented behaviour.
- Lane D tweaks are recorded only here. Lanes B/C link their folder.

## Writing style
- Plain, concise English. Short sentences. Tables where they help.
- No personal data (names, emails, phone numbers, CTC values) in docs or fixtures.
- Dates as `YYYY-MM-DD`.
- Relative links between docs.
