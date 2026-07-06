# Handoff — DSP Cleaner Calendar

_As of 2026-07-06_

## State
- GitHub Actions fully quiet: Node 20 deprecation warnings eliminated by bumping `deploy-pages` v4→v5, `upload-pages-artifact` v3→v5, `checkout` v4→v5 in both `pages.yml` and `ical-sync.yml` (commits `6ba97bc`, `a0a1f69`, pushed). Verified live: deploy run 28803505691 succeeded with zero annotations.
- Daily fail-then-succeed deploy pattern diagnosed: it's GitHub's transient server-side "Deployment failed, try again later" Pages error, NOT anything in this repo. `deploy-rescue.yml` auto-retries (up to 3 attempts, 5-min wait) and self-heals it. Expect occasional failure emails to continue; they resolve themselves.
- Local gate: `python3 -m pytest test_check_embed_freshness.py -q` — 9 passed.

## In flight
- Nothing.

## Blocked on user
- Nothing.

## Don't re-learn
- The hourly sync bot commits to main constantly — always `git pull --rebase` before pushing.
- `upload-pages-artifact` and `deploy-pages` versions must be bumped as a pair (artifact format compatibility).
- Annotation check recipe: `gh api repos/<repo>/check-runs/<job-id>/annotations`.
