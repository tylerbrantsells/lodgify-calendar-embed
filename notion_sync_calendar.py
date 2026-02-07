#!/usr/bin/env python3
import glob
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

LOG = logging.getLogger("notion-sync")
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
LOG.addHandler(_handler)

ENV_FILE = os.getenv("ENV_FILE", ".env")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID")

ICS_DIR = os.getenv("ICS_DIR", ".")
ICS_GLOB = os.getenv("ICS_GLOB", "*.ics")

TITLE_PREFIX = os.getenv("TITLE_PREFIX", "RES-")
CLOSED_PREFIX = os.getenv("CLOSED_PREFIX", "CLOSED-")
ARCHIVE_MISSING = os.getenv("ARCHIVE_MISSING", "true").lower() in {"1", "true", "yes"}

SOURCE_LABEL = os.getenv("SOURCE_LABEL", "Lodgify iCal")


def _load_env_file(path):
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as exc:
        LOG.warning("Failed to read %s: %s", path, exc)


def _slug_uid(uid):
    return re.sub(r"[^A-Za-z0-9]", "", uid or "")[:8]


def _parse_date(value):
    if not value:
        return None
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _unfold_ics_lines(raw_text):
    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded = []
    for line in lines:
        if not line:
            continue
        if line.startswith(" ") or line.startswith("\t"):
            if unfolded:
                unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _parse_ics_file(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        lines = _unfold_ics_lines(handle.read())

    events = []
    current = {}
    in_event = False

    for line in lines:
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
            continue
        if line == "END:VEVENT":
            if current.get("uid") and current.get("dtstart") and current.get("dtend"):
                events.append(current)
            in_event = False
            current = {}
            continue
        if not in_event:
            continue

        if line.startswith("UID:"):
            current["uid"] = line.split(":", 1)[1].strip()
        elif line.startswith("SUMMARY:"):
            current["summary"] = line.split(":", 1)[1].strip()
        elif line.startswith("DTSTART"):
            current["dtstart"] = line.split(":", 1)[1].strip()
        elif line.startswith("DTEND"):
            current["dtend"] = line.split(":", 1)[1].strip()

    return events


def _collect_events():
    pattern = os.path.join(ICS_DIR, ICS_GLOB)
    paths = sorted(glob.glob(pattern))
    if not paths:
        LOG.warning("No .ics files found at %s", pattern)
        return []

    all_events = []
    for path in paths:
        property_name = os.path.basename(path)
        if property_name.lower().endswith(".ics"):
            property_name = property_name[:-4]
        property_name = property_name.replace(" - availability", "").strip()

        for event in _parse_ics_file(path):
            event["property"] = property_name
            all_events.append(event)

    return all_events


def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _notion_request(method, path, payload=None, params=None):
    url = f"https://api.notion.com/v1{path}"
    for attempt in range(6):
        response = requests.request(
            method,
            url,
            headers=_notion_headers(),
            json=payload,
            params=params,
            timeout=30,
        )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            sleep_for = 2 ** attempt
            if retry_after and retry_after.isdigit():
                sleep_for = int(retry_after)
            LOG.warning("Notion rate limit hit; sleeping %ss", sleep_for)
            time.sleep(sleep_for)
            continue
        if not (200 <= response.status_code < 300):
            raise RuntimeError(
                f"Notion API error {response.status_code}: {response.text}"
            )
        return response.json()
    raise RuntimeError("Notion API error: too many retries")


def _create_database(parent_page_id):
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "Lodgify Calendar Sync"}}],
        "properties": {
            "Name": {"title": {}},
            "UID": {"rich_text": {}},
            "Property": {"select": {}},
            "Type": {"select": {}},
            "Stay": {"date": {}},
            "Check-in": {"date": {}},
            "Check-out": {"date": {}},
            "Source": {"rich_text": {}},
            "Last Sync": {"date": {}},
        },
    }
    data = _notion_request("POST", "/databases", payload=payload)
    return data.get("id")


def _query_database(database_id):
    results = []
    payload = {"page_size": 100}
    while True:
        data = _notion_request(
            "POST", f"/databases/{database_id}/query", payload=payload
        )
        results.extend(data.get("results", []))
        if data.get("has_more"):
            payload["start_cursor"] = data.get("next_cursor")
        else:
            break
    return results


def _extract_uid_from_page(page):
    props = page.get("properties") or {}
    uid_prop = props.get("UID") or {}
    rich = uid_prop.get("rich_text") or []
    if rich and isinstance(rich, list):
        return rich[0].get("plain_text") or ""
    return ""


def _build_page_payload(event, sync_time):
    uid = event["uid"]
    summary = (event.get("summary") or "").strip()
    event_type = "Closed Period" if summary.lower() == "closed period" else "Reservation"

    dtstart = _parse_date(event["dtstart"])
    dtend = _parse_date(event["dtend"])
    if not dtstart or not dtend:
        return None

    stay_end = dtend - timedelta(days=1) if dtend > dtstart else dtend
    title_prefix = CLOSED_PREFIX if event_type == "Closed Period" else TITLE_PREFIX
    title = f"{title_prefix}{_slug_uid(uid)}"

    stay_range = {"start": dtstart.isoformat()}
    if stay_end:
        stay_range["end"] = stay_end.isoformat()

    return {
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
            "UID": {"rich_text": [{"text": {"content": uid}}]},
            "Property": {"select": {"name": event["property"]}},
            "Type": {"select": {"name": event_type}},
            "Stay": {"date": stay_range},
            "Check-in": {"date": {"start": dtstart.isoformat()}},
            "Check-out": {"date": {"start": dtend.isoformat()}},
            "Source": {"rich_text": [{"text": {"content": SOURCE_LABEL}}]},
            "Last Sync": {"date": {"start": sync_time}},
        }
    }


def _prop_text(props, name):
    prop = props.get(name) or {}
    rich = prop.get("rich_text") or prop.get("title") or []
    if rich and isinstance(rich, list):
        return rich[0].get("plain_text") or ""
    return ""


def _prop_select(props, name):
    prop = props.get(name) or {}
    select = prop.get("select") or {}
    if isinstance(select, dict):
        return select.get("name") or ""
    return ""


def _prop_date(props, name):
    prop = props.get(name) or {}
    date_val = prop.get("date") or {}
    if isinstance(date_val, dict):
        return date_val.get("start"), date_val.get("end")
    return None, None


def _page_needs_update(page, desired_props):
    props = page.get("properties") or {}

    if _prop_text(props, "UID") != _prop_text(desired_props, "UID"):
        return True
    if _prop_select(props, "Property") != _prop_select(desired_props, "Property"):
        return True
    if _prop_select(props, "Type") != _prop_select(desired_props, "Type"):
        return True
    if _prop_text(props, "Name") != _prop_text(desired_props, "Name"):
        return True
    if _prop_text(props, "Source") != _prop_text(desired_props, "Source"):
        return True

    stay_start, stay_end = _prop_date(props, "Stay")
    desired_stay_start, desired_stay_end = _prop_date(desired_props, "Stay")
    if stay_start != desired_stay_start or stay_end != desired_stay_end:
        return True

    checkin_start, _ = _prop_date(props, "Check-in")
    desired_checkin, _ = _prop_date(desired_props, "Check-in")
    if checkin_start != desired_checkin:
        return True

    checkout_start, _ = _prop_date(props, "Check-out")
    desired_checkout, _ = _prop_date(desired_props, "Check-out")
    if checkout_start != desired_checkout:
        return True

    return False


def _upsert_pages(database_id, events):
    existing_pages = _query_database(database_id)
    uid_to_page = {(_extract_uid_from_page(p) or ""): p for p in existing_pages}

    sync_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    created = 0
    updated = 0
    seen_uids = set()

    for event in events:
        uid = event.get("uid") or ""
        if not uid:
            continue
        seen_uids.add(uid)

        payload = _build_page_payload(event, sync_time)
        if not payload:
            continue

        page = uid_to_page.get(uid)
        if page:
            if _page_needs_update(page, payload["properties"]):
                _notion_request(
                    "PATCH",
                    f"/pages/{page['id']}",
                    payload=payload,
                )
                updated += 1
        else:
            payload_with_parent = dict(payload)
            payload_with_parent["parent"] = {"database_id": database_id}
            _notion_request(
                "POST",
                "/pages",
                payload=payload_with_parent,
            )
            created += 1

    archived = 0
    if ARCHIVE_MISSING:
        for uid, page in uid_to_page.items():
            if uid and uid not in seen_uids:
                _notion_request(
                    "PATCH",
                    f"/pages/{page['id']}",
                    payload={"archived": True},
                )
                archived += 1

    return created, updated, archived


def main():
    _load_env_file(ENV_FILE)
    global NOTION_TOKEN, NOTION_DATABASE_ID, NOTION_PARENT_PAGE_ID
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
    NOTION_PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID")

    if not NOTION_TOKEN:
        LOG.error("Missing NOTION_TOKEN.")
        return 1

    if not NOTION_DATABASE_ID:
        if not NOTION_PARENT_PAGE_ID:
            LOG.error("Missing NOTION_PARENT_PAGE_ID to create database.")
            return 1
        LOG.info("Creating Notion database...")
        NOTION_DATABASE_ID = _create_database(NOTION_PARENT_PAGE_ID)
        LOG.info("Created database_id=%s", NOTION_DATABASE_ID)
        print(NOTION_DATABASE_ID)
        return 0

    events = _collect_events()
    LOG.info("Parsed %s events from %s", len(events), ICS_DIR)

    created, updated, archived = _upsert_pages(NOTION_DATABASE_ID, events)
    LOG.info(
        "Sync complete. Created=%s Updated=%s Archived=%s",
        created,
        updated,
        archived,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
