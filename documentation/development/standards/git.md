# Git standard

## Branches
- `main` is the stable branch.
- One branch per feature or change:

| Work | Branch name |
|---|---|
| Lane A, new capability | `feature/<capability>` (e.g. `feature/review-dashboard`) |
| Lane B, material change | `change/<capability>-<change>` |
| Lane C, small change / fix | `fix/<change>` or `change/<change>` |
| Docs only | `docs/<topic>` |

- Lane D tweaks can go on the current branch.
- The AI commits only when the developer asks.

## Commit messages
- Imperative mood, short summary line (≤ 72 chars), optional body explaining *why*.
- Prefix with the area when useful: `scanner: wait for sign-in before reading the pane`.
- Reference the spec or change folder for Lane A/B/C work:
  `Refs: documentation/development/changes/<change>/`.
- One logical change per commit. Don't mix refactors with behaviour changes.

## Never commit

| Path / kind | Why |
|---|---|
| `resumes/` (except `resumes.example.yaml`) | Personal documents |
| `profile.yaml` | Personal facts |
| `config/settings.yaml` | Personal settings |
| `data/` (`jobs.db`, `resume_profiles.json`, `decisions.jsonl`, `screenshots/`) | Personal job history and derived data |
| `browser_profile/` | Indeed session cookies |
| Secrets of any kind (tokens, passwords, keys) | Credentials |
| `.venv/`, caches | Build artefacts |

These are already in `.gitignore`. Still check `git status` and the staged diff before every
commit, and never use `git add -f` on these paths. Test fixtures must not contain personal data
(scrub real pages before saving them under `tests/fixtures/`).

## Approval files
- `plan-approval.md` is written by the developer, or recorded by the AI from the developer's
  explicit chat approval of that plan (ADR-0005). The AI commits it only when asked, and never
  edits an existing approval.
- The "Approved commit hash" in it is the commit that contains the approved spec and plan.
