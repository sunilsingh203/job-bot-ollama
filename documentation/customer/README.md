# Customer requirements

jobbot is a personal tool, so the "customer" is the developer. Its requirements are the
developer's own goals for finding and applying to jobs.

## Where the requirements are today

| Source | What it holds |
|---|---|
| `CLAUDE.md`, "Non-negotiable rules" | The safety rules every feature must keep |
| `CLAUDE.md`, "Decisions so far" | Target platform (Indeed India), apply mode (approve before submit), job types ("Easily apply" only), targets (India + remote), resume axes (role track × company type), cover letters only when required, the LLM |
| `CLAUDE.md`, "Pipeline" | The SCAN → FILTER → DECIDE → REVIEW → FILL → SUBMIT flow and the job status lifecycle |
| `documentation/development/features/<capability>/specification.md` | The agreed behaviour of each built capability (`resume-matcher`, `indeed-scanner`, `job-store`) |

`/define-feature` reads this folder, `CLAUDE.md` and the architecture docs before drafting a spec.

## What belongs in this folder

Raw source material that feeds specs. Keep it factual and dated. Examples:

- **Job-platform notes**: how Indeed's "Easily apply" flow looks step by step, the kinds of
  screening questions seen, notes on Wellfound, Greenhouse or Lever for later platforms.
- **Indeed observations**: page structure changes, redirects, Cloudflare behaviour, sign-in
  redirects, rate limits noticed (e.g. "2026-11-21: `/viewjob` redirects logged-out users to
  sign-in"). Use one file per topic, e.g. `indeed-observations.md`.
- **Goals and preferences**: target roles, locations, company types, what makes a job worth
  applying to, changes in experience level.
- **Review feedback**: patterns from jobs the LLM decided wrongly, to turn into fixtures and rules.

Don't put personal data here (resumes, contact details, CTC figures, account details). Those stay in
the gitignored `resumes/` and `profile.yaml`. Screenshots stay in `data/screenshots/`.
