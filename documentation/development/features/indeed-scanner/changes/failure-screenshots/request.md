# Request: failure-screenshots

> Lane B (change to `indeed-scanner`; touches the Indeed integration). Drafted by Claude at the
> developer's request on 2026-11-27 from the as-built review. The developer may edit it.
> Next: `/define-feature indeed-scanner/changes/failure-screenshots` → `change-definition.md`.

| | |
|---|---|
| Requested by | the developer |
| Date | 2026-11-27 |
| Related capability | `indeed-scanner` |
| Mistakes log | M-001 (CLAUDE.md promised this, but it was never built) |

## What
When the scanner hits something unexpected on Indeed, save a screenshot (and the page HTML) to
`data/screenshots/` and print the path. Then fail loudly or skip, as decided in the spec. This is
already a rule in CLAUDE.md ("fail loudly with a screenshot saved to `data/screenshots/`"), but no
code does it.

Candidate failure points in `src/jobbot/platforms/indeed/scanner.py`:
- `page.goto` raises an error (network, timeout). Today this ends in a raw traceback.
- The results page loads but has no job cards (`_load_results` returns `None`). This could be the
  real end of results, or Indeed may have changed its page.
- No job JSON is found, so the parser falls back to reading the DOM (a sign that Indeed changed
  its page).
- A job description pane can't be read (`description_failures`).
- `wait_for_human` times out on a Cloudflare check or sign-in page.

## Why
Indeed's pages will change. Without a screenshot and the HTML from the moment of failure, the
selectors in `parse.py` can't be fixed without re-running the scan. Re-running means more page
loads on your account.

## Done when
- Each chosen failure point writes `data/screenshots/<timestamp>_<reason>[_<jobkey>].png` (and the
  `.html`, if the spec says so), and the scan output shows the path.
- Writing a screenshot never crashes the scan. If the screenshot itself fails, a warning is logged
  and the scan carries on.
- `data/` stays gitignored. Nothing leaves the machine.
- Unit tests cover the file naming and the "screenshot failure doesn't crash" rule with a fake page.

## Open questions for /define-feature
1. Which failure points should save a screenshot? (All of the above, or only some.)
2. Save the page HTML as well? It's very useful for fixing `parse.py`, but the pages can contain
   your name if you're logged in. It stays local in gitignored `data/`.
3. Keep screenshots forever, or keep only the last N or the last N days?
4. After a screenshot, should the scan stop or carry on to the next job or page?

## Notes
- From the as-built review (2026-11-26): indeed-scanner open question 1.

## Decisions (2026-11-27, developer in chat)
Answers to the open questions above, given by the developer in chat:
1. **Failure points:** all five listed under "What":
   - `page.goto` error
   - results page with no cards
   - DOM fallback used (job JSON missing)
   - description pane unreadable
   - `wait_for_human` timeout
2. **What to save:** a PNG screenshot **and** the page HTML, to `data/screenshots/` (local,
   gitignored). The scan output prints the path.
3. **Retention:** keep the newest **50** screenshot sets and delete older ones automatically.
4. **After a failure:** skip that item (the job or the page) and carry on, **except** a page-load
   (`goto`) error, which **stops the scan** after the screenshot is saved.
5. Writing a screenshot must never crash the scan. If it fails, print a warning and carry on.

Not decided yet (recorded as open questions in `change-definition.md`, each with a recommendation):
- Should "results page with no cards" be told apart from a genuine end of results before taking a
  screenshot (to avoid noise)?
- Should the retention count be a config key (e.g. `scan.screenshots_keep`)?
- Does the DOM-fallback case need a screenshot every time, or once per run?

### Further decisions (2026-11-27, developer in chat, after the change-definition draft)
The open questions in `change-definition.md` were answered as follows:
- **OQ-1 (no cards):** save a `no_cards` snapshot only when the **first page** of a search has no
  cards, or when the results reload inside the description retry shows none. A later empty page is
  a genuine end of results and saves nothing.
- **OQ-2 (retention count):** a config key, **`browser.screenshots_keep`** (default 50).
- **OQ-3 (DOM fallback):** one snapshot **per scan run** (the first DOM-fallback page), plus one
  line in the end-of-scan summary.
- **OQ-4 (`wait_for_human` timeout):** **skip the item and carry on** (save the screenshot and
  HTML, skip that page or job, continue the scan) instead of stopping the scan. The developer chose
  this knowing it means more Indeed requests while a check may still be showing. It is a deliberate
  departure from the earlier "stop the scan" behaviour (spec BR-3 / AC-20) and sits in tension with
  safety rule 3 (protect the Indeed account). The bot still never automates past a check: every new
  check waits for the human again.
- **New open question (OQ-5):** stop the scan after **2 consecutive** human-wait timeouts? Claude
  recommends yes. Left for the approver to decide at plan approval.
- Assumptions **A-1..A-7** in `change-definition.md` are accepted.
- A page-load (`goto`) error still **stops the scan** after the screenshot (decided earlier).

### Decisions at approval (2026-11-27, developer in chat)
- **OQ-5 guard: yes.** Stop the scan after 2 consecutive human-wait timeouts.
- **A-8 confirmed:** a human-wait timeout on a results page ends that search's paging.
