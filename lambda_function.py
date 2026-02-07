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
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SES_EMAIL = os.getenv("SES_EMAIL", "hello@designspark.properties")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "US/Eastern")
DEFAULT_CHECKIN_TIME = os.getenv("DEFAULT_CHECKIN_TIME", "12:30")
DEFAULT_CHECKOUT_TIME = os.getenv("DEFAULT_CHECKOUT_TIME", "13:00")
IDEMPOTENCY_TABLE = os.getenv("IDEMPOTENCY_TABLE")
IDEMPOTENCY_TTL_DAYS = int(os.getenv("IDEMPOTENCY_TTL_DAYS", "0"))
MATCH_TIME_TOLERANCE_MINUTES = int(os.getenv("MATCH_TIME_TOLERANCE_MINUTES", "15"))

DUPLICATE_CODE_IS_SUCCESS = os.getenv("DUPLICATE_CODE_IS_SUCCESS", "true").lower() in {
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
PROPERTY_TIMEZONE_MAPPING = _load_json_env("PROPERTY_TIMEZONE_MAPPING_JSON", {})

PROPERTY_NAME_TO_ID = {v.strip().lower(): k for k, v in PROPERTY_NAME_MAPPING.items()}

ses_client = boto3.client("ses", region_name=AWS_REGION)
dynamodb_resource = (
    boto3.resource("dynamodb", region_name=AWS_REGION) if IDEMPOTENCY_TABLE else None
)


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


def _put_booking_record(record):
    table = _get_idempotency_table()
    if not table or not record:
        return
    try:
        table.put_item(Item=record)
    except ClientError as exc:
        LOG.error("Failed to write idempotency record: %s", exc)


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


def _resolve_property_name(property_id, booking, data):
    return (
        PROPERTY_NAME_MAPPING.get(property_id)
        or booking.get("property_name")
        or booking.get("propertyName")
        or data.get("property_name")
        or data.get("propertyName")
        or "Your Rental"
    )


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


def _resolve_booking_source(booking, data):
    return (booking.get("source") or data.get("source") or "").strip().lower()


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
    headers = {"Authorization": f"Bearer {SEAM_API_KEY}"}
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


def _find_matching_access_code(device_id, code, starts_at, ends_at):
    target_start = _parse_seam_datetime(starts_at)
    target_end = _parse_seam_datetime(ends_at)
    if not target_start or not target_end:
        return None

    tolerance = timedelta(minutes=MATCH_TIME_TOLERANCE_MINUTES)
    for entry in _list_access_codes(device_id):
        if str(entry.get("code")) != str(code):
            continue
        entry_start = _parse_seam_datetime(entry.get("starts_at"))
        entry_end = _parse_seam_datetime(entry.get("ends_at"))
        if not entry_start or not entry_end:
            continue
        if abs(entry_start - target_start) > tolerance:
            continue
        if abs(entry_end - target_end) > tolerance:
            continue
        return entry

    return None


def _delete_access_code_by_id(access_code_id, device_id=None):
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

    LOG.error(
        "Failed to delete access_code_id=%s: %s %s",
        access_code_id,
        response.status_code,
        response.text,
    )
    return False


def _times_match(value_a, value_b):
    dt_a = _parse_seam_datetime(value_a)
    dt_b = _parse_seam_datetime(value_b)
    if not dt_a or not dt_b:
        return False
    tolerance = timedelta(minutes=MATCH_TIME_TOLERANCE_MINUTES)
    return abs(dt_a - dt_b) <= tolerance


def _record_matches(record, desired):
    if not record:
        return False
    if str(record.get("device_id")) != str(desired.get("device_id")):
        return False
    if str(record.get("code")) != str(desired.get("code")):
        return False
    if not _times_match(record.get("starts_at"), desired.get("starts_at")):
        return False
    if not _times_match(record.get("ends_at"), desired.get("ends_at")):
        return False
    return True


def _build_record(
    booking_id,
    property_id,
    device_id,
    access_code_id,
    code,
    starts_at,
    ends_at,
    guest_name,
    code_source,
):
    record = {
        "booking_id": str(booking_id),
        "property_id": str(property_id),
        "device_id": str(device_id),
        "access_code_id": str(access_code_id) if access_code_id else "",
        "code": str(code),
        "starts_at": str(starts_at),
        "ends_at": str(ends_at),
        "guest_name": str(guest_name),
        "code_source": str(code_source),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    if IDEMPOTENCY_TTL_DAYS > 0:
        ends_dt = _parse_seam_datetime(ends_at)
        if ends_dt:
            record["ttl"] = int(ends_dt.timestamp()) + int(IDEMPOTENCY_TTL_DAYS * 86400)
    return record


def _should_process(status):
    return status in {"booked", "confirmed"}


def send_confirmation_email(guest_name, property_name, access_code, checkin_time, checkout_time):
    if not SES_EMAIL:
        LOG.warning("SES_EMAIL is not configured; skipping email.")
        return
    subject = f"Your Access Code for {property_name}"
    body = (
        f"Hello {guest_name},\n\n"
        f"Your access code for {property_name} is ready.\n\n"
        f"Access Code: {access_code}\n"
        f"Check-in: {checkin_time.strftime('%Y-%m-%d %I:%M %p %Z')}\n"
        f"Check-out: {checkout_time.strftime('%Y-%m-%d %I:%M %p %Z')}\n\n"
        "Please save this information for your stay.\n\n"
        "Best regards,\n"
        "Design Spark Properties\n"
    )
    try:
        ses_client.send_email(
            Source=SES_EMAIL,
            Destination={"ToAddresses": [SES_EMAIL]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        )
        LOG.info("Email sent to %s", SES_EMAIL)
    except ClientError as exc:
        LOG.error("SES send failed: %s", exc)


def _extract_access_code_id(response):
    try:
        data = response.json()
    except ValueError:
        return None

    for key in ("access_code_id", "id"):
        if isinstance(data.get(key), str):
            return data.get(key)

    if isinstance(data.get("access_code"), dict):
        for key in ("access_code_id", "id"):
            if isinstance(data["access_code"].get(key), str):
                return data["access_code"].get(key)

    if isinstance(data.get("data"), dict):
        for key in ("access_code_id", "id"):
            if isinstance(data["data"].get(key), str):
                return data["data"].get(key)

    return None


def _extract_error_type(response):
    try:
        data = response.json()
    except ValueError:
        return ""
    err = data.get("error") or {}
    if isinstance(err, dict):
        return str(err.get("type") or "")
    return ""


def _call_seam_create(payload):
    if not SEAM_API_KEY:
        return "error", "Missing SEAM_API_KEY", None, None

    url = f"{SEAM_API_URL}/access_codes/create"
    headers = {
        "Authorization": f"Bearer {SEAM_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
    except requests.RequestException as exc:
        LOG.error("Seam request failed: %s", exc)
        return "error", f"Seam request failed: {exc}", None, None

    if 200 <= response.status_code < 300:
        access_code_id = _extract_access_code_id(response)
        return "success", response.text, access_code_id, response.status_code

    response_text = response.text or ""
    error_type = _extract_error_type(response)
    if error_type == "duplicate_access_code":
        return "duplicate", response_text, None, response.status_code

    if (
        DUPLICATE_CODE_IS_SUCCESS
        and response.status_code in {409, 422}
        and "duplicate access code" in response_text.lower()
    ):
        return "duplicate", response_text, None, response.status_code

    LOG.error("Seam error %s: %s", response.status_code, response_text)
    return "error", response_text, None, response.status_code


def _resolve_access_code(guest_phone, booking_id):
    code = extract_last_four(guest_phone)
    if code:
        return code, "phone"

    booking_digits = _normalize_phone(str(booking_id) if booking_id is not None else "")
    if booking_digits:
        return booking_digits[-4:].zfill(4), "booking_id"

    return None, ""


def _delete_existing_code(record, device_id):
    if not record:
        return False

    access_code_id = record.get("access_code_id") or ""
    if access_code_id:
        return _delete_access_code_by_id(access_code_id, device_id=device_id)

    match = _find_matching_access_code(
        device_id,
        record.get("code"),
        record.get("starts_at"),
        record.get("ends_at"),
    )
    if match and match.get("access_code_id"):
        return _delete_access_code_by_id(match.get("access_code_id"), device_id=device_id)

    return False


def _create_with_fallback(device_id, payload, fallback_code, code_source):
    result, text, access_code_id, status_code = _call_seam_create(payload)
    if result == "success":
        return {
            "ok": True,
            "access_code_id": access_code_id,
            "code": payload["code"],
            "code_source": code_source,
            "is_duplicate": False,
        }

    if result == "duplicate":
        match = _find_matching_access_code(
            device_id, payload["code"], payload["starts_at"], payload["ends_at"]
        )
        if match:
            return {
                "ok": True,
                "access_code_id": match.get("access_code_id"),
                "code": payload["code"],
                "code_source": payload.get("code_source", "existing"),
                "is_duplicate": True,
            }

        if fallback_code and str(fallback_code) != str(payload["code"]):
            fallback_payload = dict(payload)
            fallback_payload["code"] = fallback_code
            result2, text2, access_code_id2, status_code2 = _call_seam_create(
                fallback_payload
            )
            if result2 == "success":
                return {
                    "ok": True,
                    "access_code_id": access_code_id2,
                    "code": fallback_code,
                    "code_source": "booking_id_fallback",
                    "is_duplicate": False,
                }
            if result2 == "duplicate":
                match2 = _find_matching_access_code(
                    device_id,
                    fallback_code,
                    fallback_payload["starts_at"],
                    fallback_payload["ends_at"],
                )
                if match2:
                    return {
                    "ok": True,
                    "access_code_id": match2.get("access_code_id"),
                    "code": fallback_code,
                    "code_source": "booking_id_fallback_existing",
                        "is_duplicate": True,
                    }
            LOG.error(
                "Duplicate access code collision for fallback code=%s status=%s body=%s",
                fallback_code,
                status_code2,
                text2,
            )
            return {"ok": False, "message": text2}

        LOG.error(
            "Duplicate access code collision for code=%s status=%s body=%s",
            payload.get("code"),
            status_code,
            text,
        )
        return {"ok": False, "message": text}

    return {"ok": False, "message": text}


def create_access_code(data):
    booking = data.get("booking") or data.get("reservation") or {}
    guest = data.get("guest") or booking.get("guest") or {}

    property_id = _resolve_property_id(booking, data)
    if not property_id:
        return {"statusCode": 400, "body": "Missing property id."}

    device_id = PROPERTY_LOCK_MAPPING.get(property_id)
    if not device_id:
        return {"statusCode": 400, "body": "No lock mapping found for property."}

    property_name = _resolve_property_name(property_id, booking, data)
    guest_name = _resolve_guest_name(guest, booking)
    booking_id = _resolve_booking_id(booking, data)
    guest_phone = _resolve_guest_phone(guest, booking, data)
    access_code, code_source = _resolve_access_code(guest_phone, booking_id)
    fallback_code, _ = _resolve_access_code("", booking_id)
    if not access_code:
        return {
            "statusCode": 400,
            "body": "Missing guest phone number and booking id.",
        }

    arrival_raw, departure_raw = _resolve_dates(booking, data)
    if not arrival_raw or not departure_raw:
        return {"statusCode": 400, "body": "Missing check-in or check-out dates."}

    timezone = PROPERTY_TIMEZONE_MAPPING.get(property_id, DEFAULT_TIMEZONE)
    checkin_dt = _parse_iso_datetime(arrival_raw, timezone)
    checkout_dt = _parse_iso_datetime(departure_raw, timezone)
    if not checkin_dt or not checkout_dt:
        return {"statusCode": 400, "body": "Invalid date format."}

    checkin_dt = _apply_time(checkin_dt, CHECKIN_TIME)
    checkout_dt = _apply_time(checkout_dt, CHECKOUT_TIME)

    if checkout_dt <= checkin_dt:
        return {"statusCode": 400, "body": "Checkout must be after checkin."}

    payload_data = {
        "device_id": device_id,
        "code": access_code,
        "name": guest_name[:20],
        "starts_at": checkin_dt.isoformat(),
        "ends_at": checkout_dt.isoformat(),
    }

    desired_record = {
        "device_id": device_id,
        "code": access_code,
        "starts_at": payload_data["starts_at"],
        "ends_at": payload_data["ends_at"],
    }

    existing_record = _get_booking_record(booking_id)
    if existing_record and _record_matches(existing_record, desired_record):
        LOG.info(
            "Idempotent hit for booking_id=%s; no update needed.",
            booking_id,
        )
        return {"statusCode": 200, "body": "Access code already up to date"}

    if existing_record:
        LOG.info("Booking change detected for booking_id=%s; updating code window.", booking_id)
        _delete_existing_code(existing_record, device_id)

    LOG.info(
        "Creating access code for booking_id=%s property=%s guest=%s phone=%s code=%s source=%s checkin=%s checkout=%s",
        booking_id,
        property_id,
        guest_name,
        _mask_phone(guest_phone),
        access_code,
        code_source,
        checkin_dt.isoformat(),
        checkout_dt.isoformat(),
    )

    creation = _create_with_fallback(device_id, payload_data, fallback_code, code_source)
    if creation.get("ok"):
        record = _build_record(
            booking_id=booking_id,
            property_id=property_id,
            device_id=device_id,
            access_code_id=creation.get("access_code_id"),
            code=creation.get("code"),
            starts_at=payload_data["starts_at"],
            ends_at=payload_data["ends_at"],
            guest_name=guest_name,
            code_source=creation.get("code_source"),
        )
        _put_booking_record(record)

        if creation.get("is_duplicate"):
            LOG.info("Access code already exists; skipping email.")
            return {"statusCode": 200, "body": "Access code already exists"}
        send_confirmation_email(
            guest_name,
            property_name,
            creation.get("code"),
            checkin_dt,
            checkout_dt,
        )
        return {"statusCode": 200, "body": "Access code created successfully"}

    return {"statusCode": 502, "body": creation.get("message", "Failed to create access code")}


def _process_payload(data):
    booking = data.get("booking") or data.get("reservation") or {}

    booking_id = _resolve_booking_id(booking, data)
    status = _resolve_booking_status(booking, data)
    action = _resolve_action(data)

    LOG.info(
        "Event received action=%s booking_id=%s status=%s",
        action,
        booking_id,
        status,
    )

    if not _should_process(status):
        LOG.info("Skipping booking_id=%s status=%s", booking_id, status)
        return {"statusCode": 200, "body": "Skipped non-confirmed booking"}

    return create_access_code(data)


def lambda_handler(event, context):
    data = _parse_event(event)

    if isinstance(data, list):
        results = [_process_payload(item) for item in data]
        status_code = 200 if all(r.get("statusCode", 500) < 300 for r in results) else 207
        return {"statusCode": status_code, "body": json.dumps(results)}

    if not isinstance(data, dict):
        LOG.error("Unexpected payload type: %s", type(data))
        return {"statusCode": 400, "body": "Invalid payload."}

    return _process_payload(data)
