# Small changes (Lane C)

Lane C covers bug fixes, minor behaviour changes and small CLI or config tweaks that are not tied
to one big feature and don't need a formal spec.

Examples: fix salary parsing for a new snippet format; add a `--since` flag to `jobbot jobs`;
handle a new Cloudflare page title in `is_challenge`.

**Not Lane C** (escalate to Lane B, see the workflow, section 3): anything that changes the DB
schema or status meanings, a prompt or the decision schema, a safety rule, the approval flow,
shared code (`models.py`, `db.py`, `config.py`, `llm/client.py`) in a way that changes behaviour,
or how jobbot talks to Indeed or Ollama. The AI recommends the escalation; the developer decides.

Trivial edits asked for directly in chat are Lane D and don't need a folder.

## How to start one

0. Branch `fix/<change>` from the latest `develop` (`/plan-small-change` does this for you;
   see `../standards/git.md`).
1. Create a folder `documentation/development/changes/<change>/`. Name it
   `YYYY-MM-DD-short-slug`, e.g. `2026-11-26-salary-per-month`.
2. Write `request.md` (copy `../templates/request.md`): what, why, and how you'll know it works.
   A few lines are enough.
3. Run `/plan-small-change <change>`. The AI writes `implementation-plan.md`.
4. Give the go-ahead in chat, or add `Approved to implement: <date>` to `request.md`.
5. Run `/implement-small-change <change>`. The AI implements and runs tests and lint.
6. Run `/review-small-change <change>`. The AI writes a brief `review.md` against the request.

```
changes/<change>/
├── request.md               # the developer
├── implementation-plan.md   # the AI
└── review.md                # the AI
```

If the change affects documented behaviour, also add a line to the capability's
`features/<capability>/changelog.md`.
