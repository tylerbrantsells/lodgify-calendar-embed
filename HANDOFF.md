# Handoff — DSP Cleaner Calendar

_As of 2026-08-13_

## State
- Public embed is live and fresh (`calendar_data.js` generated_at 2026-08-13T19:09:55Z). The 2026-07-20 stale-alert email was a GitHub Pages/Actions 503 (critical incident 2026-07-19T23:34Z), not a repo bug; recovered 2026-07-20T04:39Z. Same class of gap on 2026-08-06 (Actions/Pages incident + runner-not-acquired).
- `pages.yml` now has a 2h heartbeat cron (`20 */2 * * *`, commit `19c38f9`) so one missed hourly sync + cron jitter cannot leave Last-Modified stale past the 6h watchdog. `cancel-in-progress` is false so overlapping sync/heartbeat runs queue instead of aborting a live deploy (cancelled runs never trip `deploy-rescue`).
- GitHub Actions at latest majors: `checkout@v7`, `setup-python@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5`. Pages cert approved, expires 2026-10-01. `https_enforced: true`.
- `deploy-rescue.yml` hardened (`811ecfc`): skips rerun when the run is no longer failed, so it can't 403 if something else fixes the deploy during its 5-min wait.
- Daily fail-then-succeed deploy pattern is GitHub's transient server-side Pages error, NOT anything in this repo. In-job retry (`515a3ef`) + rescue + 2h heartbeat cover it. Occasional failure emails may still fire during multi-hour GitHub outages.
- Local gate: `python3 -m pytest test_check_embed_freshness.py -q` — 9 passed.

- Property onboarding documented: `docs/ADDING-A-PROPERTY.md` (human) + `.claude/skills/add-property/SKILL.md` (Claude skill). Local `.env` is source of truth for `ICS_URLS_JSON`.

## In flight
- Nothing.

## Blocked on user
- Nothing.

## Don't re-learn
- The hourly sync bot commits to main constantly — always `git pull --rebase` before pushing.
- `upload-pages-artifact` and `deploy-pages` versions must be bumped as a pair (artifact format compatibility).
- Annotation check recipe: `gh api repos/<repo>/check-runs/<job-id>/annotations`.
