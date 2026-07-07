# Handoff — DSP Cleaner Calendar

_As of 2026-07-06_

## State
- GitHub Actions fully quiet, all actions at latest majors: `checkout@v7`, `setup-python@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5` (commits `6ba97bc`, `a0a1f69`, `3bab827`, pushed). Verified live 2026-07-06: full sync→deploy chain green with zero annotations.
- `deploy-rescue.yml` hardened (`811ecfc`): skips rerun when the run is no longer failed, so it can't 403 if something else fixes the deploy during its 5-min wait.
- Daily fail-then-succeed deploy pattern diagnosed: it's GitHub's transient server-side "Deployment failed, try again later" Pages error, NOT anything in this repo. `deploy-rescue.yml` auto-retries (up to 3 attempts, 5-min wait) and self-heals it. Expect occasional failure emails to continue; they resolve themselves.
- Local gate: `python3 -m pytest test_check_embed_freshness.py -q` — 9 passed.

- Property onboarding documented: `docs/ADDING-A-PROPERTY.md` (human) + `.claude/skills/add-property/SKILL.md` (Claude skill). Local `.env` is source of truth for `ICS_URLS_JSON`.
- In-job deploy retry added to `pages.yml` (`515a3ef`): transient Pages failures retry within the run, so no failure emails; rescue workflow is the backstop.

## In flight
- Nothing.

## Blocked on user
- Nothing.

## Don't re-learn
- The hourly sync bot commits to main constantly — always `git pull --rebase` before pushing.
- `upload-pages-artifact` and `deploy-pages` versions must be bumped as a pair (artifact format compatibility).
- Annotation check recipe: `gh api repos/<repo>/check-runs/<job-id>/annotations`.
