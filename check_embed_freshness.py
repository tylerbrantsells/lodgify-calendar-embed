#!/usr/bin/env python3
"""Alert if the PUBLIC calendar embed has gone stale.

The embed at calendar.designsparkproperties.com is redeployed hourly by
GitHub Actions (every "Lodgify iCal Sync" completion triggers a Pages
deploy, changes or not), so its Last-Modified should never be more than
~1h old. If it exceeds STALE_AFTER_HOURS, deploys are failing (Pages
outage, dead cron, disabled workflow...) and an alert email goes out
using the same SMTP_*/ALERT_* .env config as the sync alerts. A state
file enforces a re-alert cooldown so an ongoing outage doesn't email
every hour. The runner invokes this non-fatally: a monitoring failure
must never block the Notion sync.
"""
import email.utils
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from notion_sync_calendar import _load_env_file  # the shared .env loader

SITE_URL = "https://calendar.designsparkproperties.com/"
# GitHub's "hourly" schedule cron routinely lags: observed real gaps of
# 3.4-4.5h between deploys on 2026-07-03. 6h stays clear of cron jitter
# while still catching genuine outages the same day.
STALE_AFTER_HOURS = 6
REALERT_COOLDOWN_HOURS = 6
STATE_PATH = os.path.join(HERE, ".freshness-alert-state.json")
TIMEOUT = 30


def is_stale(last_modified_header, now, stale_after_hours=STALE_AFTER_HOURS):
    """True when Last-Modified is older than the threshold (or unparseable)."""
    try:
        modified = email.utils.parsedate_to_datetime(last_modified_header)
    except (TypeError, ValueError):
        return True
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=timezone.utc)
    return (now - modified) > timedelta(hours=stale_after_hours)


def should_alert(state, now, cooldown_hours=REALERT_COOLDOWN_HOURS):
    """True unless a previous alert is inside the cooldown window."""
    raw = state.get("last_alert_utc")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return True
    return (now - last) >= timedelta(hours=cooldown_hours)


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def _send_stale_alert(detail, now):
    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    to_addr = os.getenv("ALERT_EMAIL_TO")
    if not (host and username and password and to_addr):
        print("freshness: alert skipped, SMTP/.env not configured", file=sys.stderr)
        return False

    msg = EmailMessage()
    msg["Subject"] = "Public calendar embed is STALE — Pages deploys failing?"
    msg["From"] = os.getenv("ALERT_EMAIL_FROM") or username
    msg["To"] = to_addr
    msg.set_content(
        f"{SITE_URL} looks stale as of {now.isoformat()}.\n\n"
        f"{detail}\n\n"
        "The embed redeploys hourly via GitHub Actions; staleness beyond "
        f"{STALE_AFTER_HOURS}h means deploys are failing. Check:\n"
        "https://github.com/tylerbrantsells/lodgify-calendar-embed/actions\n"
        "https://www.githubstatus.com/\n"
    )
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=20) as smtp:
        if os.getenv("SMTP_USE_TLS", "true").lower() != "false":
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(msg)
    print(f"freshness: STALE alert emailed to {to_addr}")
    return True


def main():
    _load_env_file(os.path.join(HERE, ".env"))
    now = datetime.now(timezone.utc)

    try:
        resp = requests.head(SITE_URL, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        last_modified = resp.headers.get("Last-Modified")
        detail = f"Last-Modified: {last_modified or 'MISSING'}"
        stale = is_stale(last_modified, now)
    except requests.RequestException as exc:
        # Unreachable site is worse than stale — same alert path.
        detail = f"Site unreachable: {type(exc).__name__}: {exc}"
        stale = True

    if not stale:
        print(f"freshness: OK ({detail})")
        return 0

    print(f"freshness: STALE ({detail})", file=sys.stderr)
    state = _load_state()
    if not should_alert(state, now):
        print("freshness: within re-alert cooldown, not emailing", file=sys.stderr)
        return 1
    try:
        if _send_stale_alert(detail, now):
            _save_state({"last_alert_utc": now.isoformat()})
    except Exception as exc:  # noqa: BLE001 — alerting must not crash the runner
        print(f"freshness: alert email failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
