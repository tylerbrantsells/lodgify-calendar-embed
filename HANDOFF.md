# Handoff — DSP Cleaner Calendar

_As of 2026-10-08_

## State
- Public embed is live. `calendar_data.js` generated_at 2026-10-08T19:15:56Z. `Last-Modified` Thu, 08 Oct 2026 19:19:46 GMT.
- From 2026-10-05 14:23Z until that deploy, the site stayed on the 5 October file. The iCal sync was green. Pages run 37324227672 stayed `queued` (build finished, deploy never started) and held group `pages-deploy`, so later runs were `cancelled`. Run 36764422215 had been `waiting` since 2026-09-30. Cancelling both let the pending run publish.
- `deploy-rescue.yml` cancels a Pages run that stays `queued` or `waiting` for more than 30 minutes, when a later Pages run completes as `cancelled`. A `failure` is still rerun after 5 minutes, and that rerun still skips a run that is no longer failed (`811ecfc`).
- `cancel-in-progress` stays false, so a new sync does not abort a deploy that is actually running. The 2h heartbeat cron remains `20 */2 * * *`.
- Pages certificate `CN=calendar.designsparkproperties.com`, notAfter 2026-11-30. `https_enforced: true`. Actions majors: `checkout@v7`, `setup-python@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5`.
- Daily fail-then-succeed deploy pattern is GitHub's transient server-side Pages error, NOT anything in this repo. In-job retry (`515a3ef`) + rescue + 2h heartbeat cover it. Occasional failure emails may still fire during multi-hour GitHub outages.
- Local gate: `python3 -m pytest test_build_calendar_data.py test_check_embed_freshness.py -q` — 15 passed.

- Property onboarding documented: `docs/ADDING-A-PROPERTY.md` (human) + `.claude/skills/add-property/SKILL.md` (Claude skill). Local `.env` is source of truth for `ICS_URLS_JSON`.

## In flight
- Nothing.

## Blocked on user
- 18 Coopers Vantage stays an empty row until its Lodgify iCal URL is in `.env` `ICS_URLS_JSON` and the GitHub secret. Then remove the name from `placeholder_properties.json`.

## Don't re-learn
- The hourly sync bot commits to main constantly — always `git pull --rebase` before pushing.
- `upload-pages-artifact` and `deploy-pages` versions must be bumped as a pair (artifact format compatibility).
- Annotation check recipe: `gh api repos/<repo>/check-runs/<job-id>/annotations`.
- A `pending` Pages run with no jobs is waiting. The holder is the run whose status is `queued` or `waiting`. Cancel the holder. Renaming the concurrency group only leaves that run behind.
