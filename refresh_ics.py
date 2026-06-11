#!/usr/bin/env python3
"""Refresh the local Lodgify .ics feeds for the Notion cleaner-calendar sync.

ALL-OR-ABORT: notion_sync_calendar.py runs with ARCHIVE_MISSING=true, so a
partial feed set would mass-archive real reservations from the cleaners'
Notion calendar. If ANY feed fails to download or is not an ICS calendar,
NOTHING is replaced on disk, an alert email goes out (reusing
build_calendar_data._send_alert_email), and the run exits non-zero so the
runner never reaches the sync step. Uses requests (bundled certifi) — no
ICS_INSECURE_SSL needed on this path.
"""
import json
import os
import sys
import tempfile

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from notion_sync_calendar import _load_env_file  # the shared .env loader

TIMEOUT = 30


def main():
    # Load .env BEFORE importing build_calendar_data: its SMTP_*/ALERT_* module
    # constants are read from os.environ at import time.
    _load_env_file(os.path.join(HERE, ".env"))

    raw = os.getenv("ICS_URLS_JSON")
    if not raw:
        print("refresh_ics: ICS_URLS_JSON missing from .env", file=sys.stderr)
        return 1
    try:
        feeds = json.loads(raw)
    except ValueError:
        print("refresh_ics: ICS_URLS_JSON is not valid JSON", file=sys.stderr)
        return 1
    if not isinstance(feeds, dict) or not feeds:
        print("refresh_ics: expected a non-empty {name: url} dict", file=sys.stderr)
        return 1

    failures = []
    staged = {}
    for name, url in feeds.items():
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            body = resp.text
            if "BEGIN:VCALENDAR" not in body:
                raise ValueError("response is not an ICS calendar")
            staged[name] = body
        except Exception as exc:  # noqa: BLE001 — every feed failure is collected
            failures.append({"property": name, "source": "lodgify ics", "error": f"{type(exc).__name__}: {exc}"})

    if failures:
        names = ", ".join(f["property"] for f in failures)
        print(f"refresh_ics: ABORT (all-or-nothing) — failed feeds: {names}", file=sys.stderr)
        try:
            from build_calendar_data import _send_alert_email
            _send_alert_email(failures)
        except Exception as alert_exc:  # noqa: BLE001 — alerting never masks the failure
            print(f"refresh_ics: alert email failed: {type(alert_exc).__name__}", file=sys.stderr)
        return 1

    # Every feed fetched clean -> atomic replace, matching the existing
    # "<Name> - availability.ics" convention notion_sync keys property names from.
    for name, body in staged.items():
        dest = os.path.join(HERE, f"{name} - availability.ics")
        fd, tmp = tempfile.mkstemp(dir=HERE, suffix=".ics.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    print(f"refresh_ics: {len(staged)} feeds refreshed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
