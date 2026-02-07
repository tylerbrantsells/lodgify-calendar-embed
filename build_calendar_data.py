#!/usr/bin/env python3
import glob
import json
import os
import re
import ssl
import smtplib
from datetime import date, datetime, timezone
from email.message import EmailMessage
from urllib.request import Request, urlopen

ICS_DIR = os.getenv("ICS_DIR", ".")
ICS_GLOB = os.getenv("ICS_GLOB", "*.ics")
OUTPUT_JSON = os.getenv("OUTPUT_JSON", "calendar_data.json")
OUTPUT_JS = os.getenv("OUTPUT_JS", "calendar_embed/calendar_data.js")
PROPERTY_BLOCKS_JSON = os.getenv("PROPERTY_BLOCKS_JSON")
ICS_REQUEST_TIMEOUT = int(os.getenv("ICS_REQUEST_TIMEOUT", "20"))
ICS_USER_AGENT = os.getenv("ICS_USER_AGENT", "LodgifyCalendarSync/1.0")
ICS_INSECURE_SSL = os.getenv("ICS_INSECURE_SSL", "false").lower() in {"1", "true", "yes"}
CALENDAR_MIN_DATE = os.getenv("CALENDAR_MIN_DATE", "2026-01-01")

PROPERTY_ORDER_JSON = os.getenv("PROPERTY_ORDER_JSON")

ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "hello@designspark.properties")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}
ALERT_DEDUPE_PATH = os.getenv("ALERT_DEDUPE_PATH", ".sync_alerts.json")
ALERT_DEDUPE_WINDOW_HOURS = int(os.getenv("ALERT_DEDUPE_WINDOW_HOURS", "24"))


def _load_dotenv():
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"").strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()
ICS_URLS_JSON = os.getenv("ICS_URLS_JSON")
PROPERTY_BLOCKS_JSON = os.getenv("PROPERTY_BLOCKS_JSON")
PROPERTY_ORDER_JSON = os.getenv("PROPERTY_ORDER_JSON")
ICS_INSECURE_SSL = os.getenv("ICS_INSECURE_SSL", "false").lower() in {"1", "true", "yes"}
CALENDAR_MIN_DATE = os.getenv("CALENDAR_MIN_DATE", "2026-01-01")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "hello@designspark.properties")
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}
ALERT_DEDUPE_PATH = os.getenv("ALERT_DEDUPE_PATH", ".sync_alerts.json")
ALERT_DEDUPE_WINDOW_HOURS = int(os.getenv("ALERT_DEDUPE_WINDOW_HOURS", "24"))




def _property_sort_key(name):
    match = re.match(r"\s*(\d+)", name or "")
    if match:
        return (0, int(match.group(1)), (name or "").lower())
    return (1, (name or "").lower())


def _sort_properties(properties):
    if PROPERTY_ORDER_JSON:
        try:
            order = json.loads(PROPERTY_ORDER_JSON)
            if isinstance(order, list):
                order_index = {
                    str(name).strip().lower(): idx for idx, name in enumerate(order)
                }
                return sorted(
                    properties,
                    key=lambda prop: (
                        order_index.get(str(prop.get("name", "")).strip().lower(), 9999),
                        _property_sort_key(prop.get("name", "")),
                    ),
                )
        except Exception:
            pass
    return sorted(properties, key=lambda prop: _property_sort_key(prop.get("name", "")))


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


def _extract_calendar_name(lines):
    for line in lines:
        if line.startswith("X-WR-CALNAME:"):
            return line.split(":", 1)[1].strip()
        if line.startswith("X-WR-CALDESC:"):
            return line.split(":", 1)[1].strip()
        if line.startswith("NAME:"):
            return line.split(":", 1)[1].strip()
    return ""


def _parse_ics_content(raw_text):
    lines = _unfold_ics_lines(raw_text)

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

    return events, _extract_calendar_name(lines)


def _parse_ics_file(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return _parse_ics_content(handle.read())


def _fetch_ics(url):
    request = Request(url, headers={"User-Agent": ICS_USER_AGENT})
    context = None
    if ICS_INSECURE_SSL:
        context = ssl._create_unverified_context()
    with urlopen(request, timeout=ICS_REQUEST_TIMEOUT, context=context) as response:
        return response.read().decode("utf-8", errors="ignore")


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


def _load_blocks():
    if PROPERTY_BLOCKS_JSON:
        try:
            data = json.loads(PROPERTY_BLOCKS_JSON)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _load_sources():
    sources = []
    if ICS_URLS_JSON:
        try:
            data = json.loads(ICS_URLS_JSON)
        except Exception:
            data = None
        if isinstance(data, dict):
            for name, url in data.items():
                sources.append({"name": str(name), "url": str(url)})
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    sources.append(
                        {"name": str(item.get("name") or ""), "url": str(item.get("url") or "")}
                    )
                elif isinstance(item, str):
                    sources.append({"name": "", "url": item})

    if not sources:
        pattern = os.path.join(ICS_DIR, ICS_GLOB)
        for path in sorted(glob.glob(pattern)):
            sources.append({"name": "", "path": path})

    return sources




def _load_alert_state(path):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return {}


def _save_alert_state(path, state):
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(state, handle)
    except Exception:
        pass


def _filter_alerts(failures):
    if not failures:
        return []
    state = _load_alert_state(ALERT_DEDUPE_PATH)
    now = datetime.datetime.now(datetime.timezone.utc)
    window = datetime.timedelta(hours=ALERT_DEDUPE_WINDOW_HOURS)
    keep = []
    for failure in failures:
        key = failure.get('property') or failure.get('source') or 'unknown'
        last_iso = state.get(key)
        last = None
        if last_iso:
            try:
                last = datetime.datetime.fromisoformat(last_iso)
            except Exception:
                last = None
        if not last or (now - last) > window:
            keep.append(failure)
            state[key] = now.isoformat()
    _save_alert_state(ALERT_DEDUPE_PATH, state)
    return keep

def _send_alert_email(failures):
    if not failures or not ALERT_EMAIL_TO:
        return False

    failures = _filter_alerts(failures)
    if not failures:
        return False
    if not (SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD):
        print("Email alert skipped: SMTP not configured.")
        return False

    msg = EmailMessage()
    msg["Subject"] = f"Lodgify iCal sync failed for {len(failures)} properties"
    msg["From"] = ALERT_EMAIL_FROM or SMTP_USERNAME
    msg["To"] = ALERT_EMAIL_TO

    lines = ["Lodgify iCal sync failures:", ""]
    for failure in failures:
        lines.append(f"Property: {failure.get('property')}")
        lines.append(f"Source: {failure.get('source')}")
        lines.append(f"Error: {failure.get('error')}")
        lines.append("")

    msg.set_content("\n".join(lines))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            if SMTP_USE_TLS:
                smtp.starttls()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)
        print(f"Alert email sent to {ALERT_EMAIL_TO}")
        return True
    except Exception as exc:
        print(f"Email alert failed: {exc}")
        return False


def _collect_events():
    sources = _load_sources()
    properties = []
    blocks = _load_blocks()
    today_str = date.today().isoformat()
    min_date = _parse_date(CALENDAR_MIN_DATE) or date(2026, 1, 1)
    failures = []

    for source in sources:
        raw_text = ""
        property_name = source.get("name") or ""
        source_label = source.get("url") or source.get("path") or "unknown"

        try:
            if source.get("url"):
                raw_text = _fetch_ics(source["url"])
            elif source.get("path"):
                with open(source["path"], "r", encoding="utf-8", errors="ignore") as handle:
                    raw_text = handle.read()
        except Exception as exc:
            failures.append(
                {
                    "property": property_name or "unknown",
                    "source": source_label,
                    "error": str(exc),
                }
            )
            continue

        if not raw_text:
            failures.append(
                {
                    "property": property_name or "unknown",
                    "source": source_label,
                    "error": "empty response",
                }
            )
            continue

        events, cal_name = _parse_ics_content(raw_text)

        if not property_name:
            property_name = cal_name
        if not property_name:
            if source.get("path"):
                property_name = os.path.basename(source["path"])
            elif source.get("url"):
                property_name = source["url"].split("/")[-1]

        if property_name.lower().endswith(".ics"):
            property_name = property_name[:-4]
        property_name = property_name.replace(" - availability", "").strip()

        normalized_events = []
        for event in events:
            dtstart = _parse_date(event.get("dtstart"))
            dtend = _parse_date(event.get("dtend"))
            if not dtstart or not dtend:
                continue
            if dtend <= min_date:
                continue
            if dtstart < min_date:
                dtstart = min_date
            raw_summary = (event.get("summary") or "").strip()
            event_type = "closed" if raw_summary.lower() == "closed period" else "reservation"
            # Remove guest-identifying details from public output.
            summary = "Owner Block" if event_type == "closed" else "Reservation"
            normalized_events.append(
                {
                    "uid": event.get("uid"),
                    "summary": summary,
                    "type": event_type,
                    "start": dtstart.isoformat(),
                    "end": dtend.isoformat(),
                }
            )

        for block in blocks:
            if str(block.get("property", "")).strip().lower() != property_name.strip().lower():
                continue
            start = block.get("start") or today_str
            if str(start).lower() == "today":
                start = today_str
            end = block.get("end")
            if not end:
                continue
            block_start = _parse_date(str(start))
            block_end = _parse_date(str(end))
            if not block_start or not block_end:
                continue
            if block_end <= min_date:
                continue
            if block_start < min_date:
                block_start = min_date

            filtered = []
            for ev in normalized_events:
                ev_start = _parse_date(ev.get("start"))
                ev_end = _parse_date(ev.get("end"))
                if not ev_start or not ev_end:
                    continue
                overlaps = ev_start < block_end and ev_end > block_start
                if not overlaps:
                    filtered.append(ev)
            normalized_events = filtered

            normalized_events.append(
                {
                    "uid": f"manual-block-{property_name}-{block_start}-{block_end}",
                    "summary": block.get("summary") or "Closed Period",
                    "type": "closed",
                    "start": block_start.isoformat(),
                    "end": block_end.isoformat(),
                }
            )

        properties.append({"name": property_name, "events": normalized_events})

    return _sort_properties(properties), failures


def main():
    properties, failures = _collect_events()
    data = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "properties": properties,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    print(OUTPUT_JSON)

    if OUTPUT_JS:
        output_path = OUTPUT_JS
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write("window.__CALENDAR_DATA__ = ")
            json.dump(data, handle)
            handle.write(";\n")
        print(output_path)

    if failures:
        _send_alert_email(failures)


if __name__ == "__main__":
    main()
