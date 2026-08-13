# Stale-embed alerts fire when GitHub is down and the next hourly cron lags

**Problem:** `check_embed_freshness.py` emailed "Pages deploys failing" on 2026-07-20 (and again 2026-08-06) even though the repo, secrets, and calendar data were fine.

**Dead ends:** Treating it as a broken workflow/secret (`ICS_URLS_JSON`, action majors, cert `bad_authz`) — live `Last-Modified` and `calendar_data.js` were already current on 2026-08-13; Actions were green all day. The unused `calendar_data.json` on Pages still says `generated_at` 2026-02-05; the app loads `calendar_data.js`, so that file is not the stale signal.

**What worked:** Reproduce the live header first, then map the alert timestamp onto `gh run list --created` and githubstatus incidents. Jul 20 00:02 deploy 503 + rescue 503 matched a critical Actions/Pages incident at 23:34; next successful deploy was 04:39 (hourly cron jitter). Same shape Aug 6: runner-not-acquired → deploy skipped → 8.8h gap.

**The rule:** A Pages `Last-Modified` older than 6h means "no successful deploy landed," not "the calendar pipeline is broken." Confirm with (1) last green `Deploy calendar to GitHub Pages` run, (2) githubstatus Pages/Actions incidents in that window, (3) live `calendar_data.js` `generated_at` — not `calendar_data.json`.

**Applies when:** the freshness watchdog emails, or `calendar.designsparkproperties.com` looks stale.
