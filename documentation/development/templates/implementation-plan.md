# Implementation plan: <capability or change>

> Lane A: `features/<capability>/implementation-plan.md`
> Lane B: `features/<capability>/changes/<change>/implementation-plan.md`
> Lane C: `changes/<change>/implementation-plan.md` (keep it short)

| | |
|---|---|
| Spec / request | link to `specification.md`, `change-definition.md` or `request.md` |
| Author | AI agent |
| Date | YYYY-MM-DD |
| Base commit | `<git rev-parse --short HEAD>` |

## 1. What I understood
One paragraph.

## 2. Affected layers
| Layer | Impact | Notes |
|---|---|---|
| DB (migrations) | none / yes | |
| Core logic (`matcher/`, `pipeline.py`, `llm/`, `resumes/`, `platforms/`) | | |
| Interface (CLI `cli.py`, dashboard) | | |
| Config (`config.py`, `config/*.yaml`, `profile.yaml`) | | |
| Prompts (`llm/prompts.py`, version bump?) | | |
| Safety rules (`CLAUDE.md`) | | |
| Tests | | |
| Docs | | |

## 3. Database changes
List every change explicitly, or write "None".

| Migration file | Change | Reversible? |
|---|---|---|
| `src/jobbot/migrations/NNNN_name.sql` | tables / columns / indexes / constraints | yes / no (needs approval) |

## 4. Module interfaces and CLI commands
New or changed functions/classes (signature, what they return, what they raise) and CLI commands
(name, flags, output, exit behaviour).

## 5. Dashboard screens (if any)
Screen -> the module functions it calls -> the status transitions it triggers.

## 6. Test plan
| AC | Test (file::name) or check | Needs LLM? |
|---|---|---|
| AC-1 | | no |

## 7. Implementation steps
1.
2.

## 8. Risks
-

## 9. Open questions and assumptions
-

## 10. ADRs needed
- none / ADR-NNNN: <title>
