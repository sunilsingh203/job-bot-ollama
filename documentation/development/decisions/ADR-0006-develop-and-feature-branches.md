# ADR-0006: `develop` branch, with one feature branch per piece of work cut from it

- **Status:** Accepted
- **Date:** 2026-11-28

## Context
Until now, the work happened on one long-lived branch (`docs/spec-driven-workflow`), and `main`
only received it through occasional PRs. The developer asked that every new feature get its own
branch, created from the latest development branch, and that this become part of the workflow.

## Options
1. **`main` as the development branch.** Features branch from `main` and merge back into it.
2. **A separate `develop` branch.** Features branch from `develop` and merge back by PR. `main`
   only receives `develop` when the developer calls it stable.

And when the branch is created:
- **a.** at `/define-feature` or `/plan-small-change`, before the first file
- **b.** at `/implement-*`, so only the code goes on the branch

## Decision
**Option 2 + a**, chosen by the developer on 2026-11-28.
- `develop` was created from the latest work and pushed to `origin`.
- Every Lane A/B/C piece of work starts with:
  ```
  git fetch origin
  git switch develop
  git pull --ff-only origin develop
  git switch -c <branch>
  ```
  Branch names are `feature/<capability>`, `change/<capability>-<change>`, `fix/<change>` and
  `docs/<topic>`.
- This happens before the first file of the work is written: at `/define-feature` for Lanes A/B,
  and at `/plan-small-change` for Lane C. The spec, plan, approval, code, tests and review then go
  into `develop` as one PR.
- The implement, review and remediate commands check that they are on the work's own branch, and
  never commit feature work to `develop` or `main`.
- The developer merges the PRs. The AI commits and pushes only when asked.

## Consequences
- Each feature is reviewable as one PR, and `develop` always has the latest finished work.
- A feature branch can fall behind `develop`. The commands check for that and offer to merge the
  latest `develop` in. A pushed branch is never rebased without asking.
- Lane D tweaks may still go on the current branch, including `develop`.
- The open change `indeed-scanner/changes/scan-cap-and-paging` was planned before this rule.
  When it is implemented, it gets a `change/indeed-scanner-scan-cap-and-paging` branch from `develop`.
