#!/bin/zsh
# Hourly cleaner-calendar Notion sync (launchd: com.dsp.cleaner-calendar).
#
# The PUBLIC embed (calendar.designsparkproperties.com) is built and deployed
# by GitHub Actions on the remote repo — this job deliberately does NOT build
# or push it. Its sole job is the piece nothing else runs: refresh the local
# .ics feeds (all-or-abort) and sync the cleaners' Notion calendar.
# Creds: the gitignored .env in this directory (read by the scripts themselves).
set -eu

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")"

# Pinned: the framework python is the one with `requests` installed; under
# launchd, bare `python3` resolves elsewhere (no requests) — the first live
# run failed exactly that way.
PYTHON="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"

"$PYTHON" refresh_ics.py
"$PYTHON" notion_sync_calendar.py

# Independent watchdog: alert if the PUBLIC embed stops redeploying
# (Pages outage, dead cron...). Non-fatal — monitoring must never
# block or fail the sync above.
"$PYTHON" check_embed_freshness.py || echo "freshness check reported stale/unreachable (alert handled in-script)" >&2
