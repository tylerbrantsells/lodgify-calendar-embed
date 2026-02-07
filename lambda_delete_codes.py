import base64
import json
import logging
import os
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import boto3
import requests
from botocore.exceptions import ClientError

LOG = logging.getLogger()
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))

SEAM_API_KEY = os.getenv("SEAM_API_KEY")
SEAM_API_URL = os.getenv("SEAM_API_URL", "https://connect.getseam.com").rstrip("/")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "US/Eastern")
DEFAULT_CHECKIN_TIME = os.getenv("DEFAULT_CHECKIN_TIME", "12:30")
DEFAULT_CHECKOUT_TIME = os.getenv("DEFAULT_CHECKOUT_TIME", "13:00")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
IDEMPOTENCY_TABLE = os.getenv("IDEMPOTENCY_TABLE")

CLEANUP_GRACE_DAYS = float(os.getenv("CLEANUP_GRACE_DAYS", "1"))
CLEANUP_ONLY_MANAGED = os.getenv("CLEANUP_ONLY_MANAGED", "true").lower() in {
    "1",
    "true",
    "yes",
}
CLEANUP_ONLY_TIMEBOUND = os.getenv("CLEANUP_ONLY_TIMEBOUND", "true").lower() in {
    "1",
    "true",
    "yes",
}
CLEANUP_DRY_RUN = os.getenv("CLEANUP_DRY_RUN", "false").lower() in {
    "1",
    "true",
    "yes",
}

CANCELLED_STATUSES = {
    status.strip().lower()
    for status in os.getenv("CANCELLED_STATUSES", "cancelled,canceled,declined").split(",")
    if status.strip()
}
ACTION_CANCEL_KEYWORDS = {
    keyword.strip().lower()
    for keyword in os.getenv("ACTION_CANCEL_KEYWORDS", "cancel,decline").split(",")
    if keyword.strip()
}

MATCH_ENDS_AT_TOLERANCE_MINUTES = int(
    os.getenv("MATCH_ENDS_AT_TOLERANCE_MINUTES", "15")
)
ALLOW_CODE_ONLY_MATCH = os.getenv("ALLOW_CODE_ONLY_MATCH", "false").lower() in {
    "1",
    "true",
    "yes",
}

DEFAULT_PROPERTY_LOCK_MAPPING = {
    "464082": "7f3554b4-8194-455a-9c82-ea75027d3a6f",  # 59 Oak Lane
    "598609": "4679c71a-71b3-4e34-a9e6-b1bb64a00312",  # 333 Dobie
    "598610": "388365da-1107-4181-bd5a-027769888b66",  # 1923 High Ridge
    "608063": "fd831636-e600-420c-bbf6-ee3d92a135f3",  # 327 Crawfords Edge
    "618434": "cc81df46-1385-4503-b00c-a7f51eebec1e",  # 61 Bear Run
    "679039": "465c699a-be2d-42d0-af2b-c9fada675010",  # 111 Eagles Court
    "670348": "518f9beb-7b4e-485f-bb8d-977fba1a7788",  # 67 Squirrel Tree
    "717848": "e1647821-ac56-42ef-abc3-82290986e962",  # 119 Pedlars Point
}

DEFAULT_PROPERTY_NAME_MAPPING = {
    "464082": "59 Oak Lane",
    "598609": "333 Dobie",
    "598610": "1923 High Ridge",
    "608063": "327 Crawfords Edge",
    "618434": "61 Bear Run",
    "679039": "111 Eagles Court",
    "670348": "67 Squirrel Tree",
    "717848": "119 Pedlars Point",
}


def _load_json_env(name, default_value):
    raw = os.getenv(name)
    if not raw:
        return default_value
    try:
        parsed = json.loads(raw)
    except Exception:
        LOG.warning("Invalid JSON in %s; using defaults.", name)
        return default_value
    if not isinstance(parsed, dict):
        LOG.warning("Expected dict JSON for %s; using defaults.", name)
        return default_value
    return {str(k): v for k, v in parsed.items()}


PROPERTY_LOCK_MAPPING = _load_json_env(
    "PROPERTY_LOCK_MAPPING_JSON", DEFAULT_PROPERTY_LOCK_MAPPING
)
PROPERTY_NAME_MAPPING = _load_json_env(
    "PROPERTY_NAME_MAPPING_JSON", DEFAULT_PROPERTY_NAME_MAPPING
)
PROPERTY_NAME_TO_ID = {v.strip().lower(): k for k, v in PROPERTY_NAME_MAPPING.items()}

dynamodb_resource = (
    boto3.resource("dynamodb", region_name=AWS_REGION) if IDEMPOTENCY_TABLE else None
)


CHECKIN_TIME = None
CHECKOUT_TIME = None


def _parse_hhmm(value, fallback):
    try:
        parts = value.strip().split(":")
        if len(parts) != 2:
            raise ValueError("Expected HH:MM")
        hour = int(parts[0])
        minute = int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Out of range")
        return time(hour=hour, minute=minute)
    except Exception:
        return fallback


CHECKIN_TIME = _parse_hhmm(DEFAULT_CHECKIN_TIME, time(hour=12, minute=30))
CHECKOUT_TIME = _parse_hhmm(DEFAULT_CHECKOUT_TIME, time(hour=13, minute=0))


def _parse_event(event):
    data = event
    if isinstance(event, dict) and "body" in event:
        body = event.get("body")
        if event.get("isBase64Encoded") and isinstance(body, str):
            body = base64.b64decode(body).decode("utf-8")
        if isinstance(body, str):
            try:
                data = json.loads(body)
            except Exception:
                LOG.warning("Failed to JSON-decode event body; using raw body.")
                data = body
        else:
            data = body
    return data


def _get_idempotency_table():
    if not IDEMPOTENCY_TABLE or dynamodb_resource is None:
        return None
    return dynamodb_resource.Table(IDEMPOTENCY_TABLE)


def _get_booking_record(booking_id):
    table = _get_idempotency_table()
    if not table or booking_id is None:
        return None
    try:
        response = table.get_item(Key={"booking_id": str(booking_id)})
    except ClientError as exc:
        LOG.error("Failed to read idempotency record: %s", exc)
        return None
    return response.get("Item")


def _delete_booking_record(booking_id):
    table = _get_idempotency_table()
    if not table or booking_id is None:
        return
    try:
        table.delete_item(Key={"booking_id": str(booking_id)})
    except ClientError as exc:
        LOG.error("Failed to delete idempotency record: %s", exc)


def _normalize_phone(phone):
    return re.sub(r"\D", "", phone or "")


def extract_last_four(phone_number):
    digits = _normalize_phone(phone_number)
    if len(digits) < 4:
        return None
    return digits[-4:]


def _mask_phone(phone_number):
    digits = _normalize_phone(phone_number)
    if not digits:
        return ""
    if len(digits) <= 4:
        return digits
    return "*" * (len(digits) - 4) + digits[-4:]


def _resolve_property_id(booking, data):
    property_id = (
        booking.get("property_id")
        or booking.get("propertyId")
        or (booking.get("property") or {}).get("id")
        or data.get("property_id")
        or data.get("propertyId")
    )
    if property_id:
        return str(property_id).strip()

    property_name = (
        booking.get("property_name")
        or booking.get("propertyName")
        or data.get("property_name")
        or data.get("propertyName")
    )
    if property_name:
        return PROPERTY_NAME_TO_ID.get(str(property_name).strip().lower())

    return ""


def _resolve_guest_name(guest, booking):
    name = guest.get("name")
    if name:
        return str(name).strip()

    first = guest.get("first_name") or guest.get("firstName")
    last = guest.get("last_name") or guest.get("lastName")
    combined = " ".join(part for part in [first, last] if part)
    if combined:
        return combined.strip()

    return str(booking.get("guest_name") or "Guest").strip()


def _resolve_guest_phone(guest, booking, data):
    return (
        guest.get("phone_number")
        or guest.get("phone")
        or booking.get("guest_phone")
        or booking.get("phone_number")
        or data.get("guest_phone")
        or data.get("phone_number")
        or ""
    )


def _resolve_booking_id(booking, data):
    return booking.get("id") or data.get("booking_id") or data.get("id")


def _resolve_booking_status(booking, data):
    return (booking.get("status") or data.get("status") or "").strip().lower()


def _resolve_action(data):
    return (data.get("action") or data.get("event") or "").strip().lower()


def _resolve_dates(booking, data):
    arrival = (
        booking.get("date_arrival")
        or booking.get("arrival_date")
        or booking.get("check_in")
        or booking.get("checkin")
        or data.get("date_arrival")
        or data.get("arrival_date")
    )
    departure = (
        booking.get("date_departure")
        or booking.get("departure_date")
        or booking.get("check_out")
        or booking.get("checkout")
        or data.get("date_departure")
        or data.get("departure_date")
    )
    if not arrival or not departure:
        reservation = data.get("reservation") or {}
        arrival = arrival or reservation.get("date_arrival")
        departure = departure or reservation.get("date_departure")
    return arrival, departure


def _parse_iso_datetime(value, timezone):
    if not value:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    if value_str.endswith("Z"):
        value_str = value_str[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value_str)
    except ValueError:
        try:
            parsed = datetime.strptime(value_str, "%Y-%m-%d")
        except ValueError:
            return None
    tz = ZoneInfo(timezone)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _parse_seam_datetime(value):
    if not value:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    if value_str.endswith("Z"):
        value_str = value_str[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value_str)
    except ValueError:
        return None


def _apply_time(value_dt, time_value):
    return value_dt.replace(
        hour=time_value.hour,
        minute=time_value.minute,
        second=0,
        microsecond=0,
    )


def _resolve_access_code(guest_phone, booking_id):
    code = extract_last_four(guest_phone)
    if code:
        return code, "phone"

    booking_digits = _normalize_phone(str(booking_id) if booking_id is not None else "")
    if booking_digits:
        return booking_digits[-4:].zfill(4), "booking_id"

    return None, ""


def _is_cancellation_event(status, action):
    if status and status in CANCELLED_STATUSES:
        return True
    if action:
        return any(keyword in action for keyword in ACTION_CANCEL_KEYWORDS)
    return False


def _seam_post(path, payload):
    if not SEAM_API_KEY:
        raise RuntimeError("Missing SEAM_API_KEY")
    url = f"{SEAM_API_URL}{path}"
    headers = {
        "Authorization": f"Bearer {SEAM_API_KEY}",
        "Content-Type": "application/json",
    }
    return requests.post(url, headers=headers, json=payload, timeout=15)


def _seam_get(path, params):
    if not SEAM_API_KEY:
        raise RuntimeError("Missing SEAM_API_KEY")
    url = f"{SEAM_API_URL}{path}"
    headers = {
        "Authorization": f"Bearer {SEAM_API_KEY}",
    }
    return requests.get(url, headers=headers, params=params, timeout=15)


def _extract_codes_from_response(data):
    if isinstance(data, list):
        return data, {}
    if not isinstance(data, dict):
        return [], {}
    if "access_codes" in data:
        return data.get("access_codes") or [], data.get("pagination") or {}
    if "data" in data and isinstance(data.get("data"), list):
        return data.get("data"), data.get("pagination") or {}
    return [], data.get("pagination") or {}


def _list_access_codes(device_id):
    codes = []
    page_cursor = None

    while True:
        payload = {"device_id": device_id, "limit": 200}
        if page_cursor:
            payload["page_cursor"] = page_cursor

        response = _seam_post("/access_codes/list", payload)
        if response.status_code in {404, 405}:
            response = _seam_get("/access_codes/list", payload)

        if not (200 <= response.status_code < 300):
            LOG.error(
                "Failed to list access codes for device %s: %s %s",
                device_id,
                response.status_code,
                response.text,
            )
            break

        try:
            data = response.json()
        except ValueError:
            LOG.error("Invalid JSON response listing access codes for device %s", device_id)
            break

        batch, pagination = _extract_codes_from_response(data)
        codes.extend(batch)

        if isinstance(pagination, dict) and pagination.get("has_next_page"):
            page_cursor = pagination.get("next_page_cursor")
            if not page_cursor:
                break
        else:
            break

    return codes


def _delete_access_code(access_code_id, device_id=None):
    if CLEANUP_DRY_RUN:
        LOG.info("DRY_RUN: would delete access_code_id=%s", access_code_id)
        return True

    payload = {"access_code_id": access_code_id}
    if device_id:
        payload["device_id"] = device_id

    try:
        response = _seam_post("/access_codes/delete", payload)
    except RuntimeError as exc:
        LOG.error("Delete failed: %s", exc)
        return False

    if 200 <= response.status_code < 300:
        return True

    text = (response.text or "").lower()
    if response.status_code in {404, 410, 422} and "not" in text:
        LOG.info("Access code already deleted: %s", access_code_id)
        return True

    LOG.error("Failed to delete access_code_id=%s: %s %s", access_code_id, response.status_code, response.text)
    return False


def _filter_codes_for_booking(codes, access_code, checkin_dt, checkout_dt):
    matches = []
    tolerance = timedelta(minutes=MATCH_ENDS_AT_TOLERANCE_MINUTES)

    for code in codes:
        if str(code.get("code")) != str(access_code):
            continue
        if CLEANUP_ONLY_MANAGED and code.get("is_managed") is False:
            continue
        if CLEANUP_ONLY_TIMEBOUND and code.get("type") not in {None, "time_bound"}:
            continue

        ends_at = _parse_seam_datetime(code.get("ends_at"))
        if ends_at is None:
            continue
        ends_at_local = ends_at.astimezone(checkout_dt.tzinfo)
        if abs(ends_at_local - checkout_dt) > tolerance:
            continue

        starts_at = _parse_seam_datetime(code.get("starts_at"))
        if starts_at is not None:
            starts_at_local = starts_at.astimezone(checkin_dt.tzinfo)
            if abs(starts_at_local - checkin_dt) > tolerance:
                continue

        matches.append(code)

    if matches:
        return matches

    if ALLOW_CODE_ONLY_MATCH:
        for code in codes:
            if str(code.get("code")) != str(access_code):
                continue
            if CLEANUP_ONLY_MANAGED and code.get("is_managed") is False:
                continue
            if CLEANUP_ONLY_TIMEBOUND and code.get("type") not in {None, "time_bound"}:
                continue
            matches.append(code)

    return matches


def delete_codes_for_cancellation(data):
    booking = data.get("booking") or data.get("reservation") or {}
    guest = data.get("guest") or booking.get("guest") or {}

    booking_id = _resolve_booking_id(booking, data)
    property_id = _resolve_property_id(booking, data)
    if not property_id:
        return {"statusCode": 400, "body": "Missing property id."}

    device_id = PROPERTY_LOCK_MAPPING.get(property_id)
    if not device_id:
        return {"statusCode": 400, "body": "No lock mapping found for property."}

    record = _get_booking_record(booking_id)
    if record and record.get("access_code_id"):
        record_device_id = record.get("device_id") or device_id
        if _delete_access_code(record["access_code_id"], device_id=record_device_id):
            _delete_booking_record(booking_id)
            return {"statusCode": 200, "body": "Deleted access code from idempotency record"}

    guest_phone = _resolve_guest_phone(guest, booking, data)
    access_code, code_source = _resolve_access_code(guest_phone, booking_id)
    if not access_code:
        return {"statusCode": 400, "body": "Missing phone and booking id."}

    arrival_raw, departure_raw = _resolve_dates(booking, data)
    if not arrival_raw or not departure_raw:
        return {"statusCode": 400, "body": "Missing check-in or check-out dates."}

    checkin_dt = _parse_iso_datetime(arrival_raw, DEFAULT_TIMEZONE)
    checkout_dt = _parse_iso_datetime(departure_raw, DEFAULT_TIMEZONE)
    if not checkin_dt or not checkout_dt:
        return {"statusCode": 400, "body": "Invalid date format."}

    checkin_dt = _apply_time(checkin_dt, CHECKIN_TIME)
    checkout_dt = _apply_time(checkout_dt, CHECKOUT_TIME)

    LOG.info(
        "Cancel delete for booking_id=%s property_id=%s device_id=%s code=%s source=%s phone=%s",
        booking_id,
        property_id,
        device_id,
        access_code,
        code_source,
        _mask_phone(guest_phone),
    )

    codes = _list_access_codes(device_id)
    matches = _filter_codes_for_booking(codes, access_code, checkin_dt, checkout_dt)

    if not matches:
        LOG.info("No matching access code found for booking_id=%s", booking_id)
        return {"statusCode": 200, "body": "No matching access code found"}

    deleted = 0
    for code in matches:
        access_code_id = code.get("access_code_id")
        if not access_code_id:
            continue
        if _delete_access_code(access_code_id, device_id=device_id):
            deleted += 1

    if deleted > 0:
        _delete_booking_record(booking_id)

    return {"statusCode": 200, "body": f"Deleted {deleted} access code(s)"}


def cleanup_expired_codes():
    now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    cutoff = now - timedelta(days=CLEANUP_GRACE_DAYS)

    device_ids = sorted(set(PROPERTY_LOCK_MAPPING.values()))
    total_deleted = 0
    total_checked = 0

    for device_id in device_ids:
        codes = _list_access_codes(device_id)
        for code in codes:
            total_checked += 1
            if CLEANUP_ONLY_MANAGED and code.get("is_managed") is False:
                continue
            if CLEANUP_ONLY_TIMEBOUND and code.get("type") not in {None, "time_bound"}:
                continue

            ends_at = _parse_seam_datetime(code.get("ends_at"))
            if ends_at is None:
                continue
            ends_at_local = ends_at.astimezone(now.tzinfo)
            if ends_at_local > cutoff:
                continue

            access_code_id = code.get("access_code_id")
            if not access_code_id:
                continue
            if _delete_access_code(access_code_id, device_id=device_id):
                total_deleted += 1

    LOG.info("Cleanup complete. Checked=%s Deleted=%s", total_checked, total_deleted)
    return {
        "statusCode": 200,
        "body": json.dumps({"checked": total_checked, "deleted": total_deleted}),
    }


def _process_payload(data):
    booking = data.get("booking") or data.get("reservation") or {}
    status = _resolve_booking_status(booking, data)
    action = _resolve_action(data)

    if _is_cancellation_event(status, action):
        return delete_codes_for_cancellation(data)

    return {"statusCode": 200, "body": "Skipped: not a cancellation event"}


def lambda_handler(event, context):
    data = _parse_event(event)

    if isinstance(data, dict):
        mode = str(data.get("mode", "")).strip().lower()
        if mode == "cleanup":
            return cleanup_expired_codes()
        if mode == "cancel":
            return _process_payload(data)

    # Scheduled EventBridge typically includes a source key
    if isinstance(data, dict) and data.get("source") == "aws.events":
        return cleanup_expired_codes()

    if isinstance(data, list):
        results = [_process_payload(item) for item in data]
        status_code = 200 if all(r.get("statusCode", 500) < 300 for r in results) else 207
        return {"statusCode": status_code, "body": json.dumps(results)}

    if not isinstance(data, dict):
        LOG.error("Unexpected payload type: %s", type(data))
        return {"statusCode": 400, "body": "Invalid payload."}

    return _process_payload(data)
