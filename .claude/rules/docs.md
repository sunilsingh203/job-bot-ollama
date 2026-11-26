# Documentation rules

Details: `documentation/development/standards/documentation.md`, `documentation/development/AI-DEVELOPMENT-WORKFLOW.md`.

- Classify work first (Lane A/B/C/D). Governance is **standard**: Lanes A/B need a human-written `plan-approval.md` before implementation; Lanes C/D go ahead on the developer's chat go-ahead.
- **Never create, fill, edit or fake a `plan-approval.md`.** If it's missing, stop and tell the developer.
- Update docs in the same change as the code:

| Changed | Update |
|---|---|
| Capability behaviour / ACs | `features/<capability>/specification.md` + `changelog.md` |
| Schema, statuses, `data/` files, config keys | `architecture/data.md` (+ `config/settings.example.yaml`) |
| Modules or boundaries | `architecture/overview.md` |
| Safety controls | `architecture/security.md`, `.claude/rules/safety.md` |
| CLI commands / flags | `README.md`, `CLAUDE.md` Commands (ask before editing `CLAUDE.md` rules) |
| Significant choice | new ADR + `decisions/README.md` index |
| Build status of a capability | capability tables in `architecture/overview.md` and the workflow doc |

- Chat decisions that refine or override a spec get written into the spec; the repo is the record.
- If a chat instruction contradicts the spec, say so in one line, propose a resolution, follow the developer.
- If you skip a workflow step at the developer's request, say once what was skipped.
- Common-mistakes log `.claude/mistakes/common-mistakes.md`: check relevant "How to avoid" lines before finishing; add an entry when corrected or when a review finds a Claude-introduced defect; streak +1 when avoided; delete at 3/3 or when a test/lint/hook guards it. Report log changes.
- Never claim a test passed unless you ran it; paste the command and result in plans and reviews.
- No personal data in docs. Plain, concise English; dates as `YYYY-MM-DD`.
