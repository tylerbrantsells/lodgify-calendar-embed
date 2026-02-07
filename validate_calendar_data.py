#!/usr/bin/env python3
import json
from datetime import date, datetime, timedelta

DATA_PATH = "calendar_data.json"


def make_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def month_start(d):
    return d.replace(day=1)


def month_end(d):
    next_month = d.replace(day=28) + timedelta(days=4)
    return next_month.replace(day=1) - timedelta(days=1)


def add_days(d, days):
    return d + timedelta(days=days)


def half_index(day, half):
    return (day.day - 1) * 2 + (2 if half == "pm" else 1)


def iter_months(start, end):
    cursor = start.replace(day=1)
    while cursor <= end:
        yield cursor
        year = cursor.year + (cursor.month // 12)
        month = (cursor.month % 12) + 1
        cursor = cursor.replace(year=year, month=month, day=1)


def compute_span(event, month_start_d, month_end_d, reservation_checkouts):
    event_start = make_date(event["start"])
    event_end = make_date(event["end"])
    month_end_excl = month_end_d + timedelta(days=1)

    if event_end <= month_start_d or event_start >= month_end_excl:
        return None

    display_start = max(event_start, month_start_d)
    display_end = min(event_end, month_end_excl)

    days = (month_end_excl - month_start_d).days

    if event["type"] == "closed":
        starts_on_checkout = event["start"] in reservation_checkouts
        start_half = half_index(display_start, "pm" if starts_on_checkout else "am")
        end_half = days * 2 + 1 if event_end >= month_end_excl else half_index(display_end, "am")
        return start_half, end_half

    start_half = half_index(display_start, "am") if event_start < month_start_d else half_index(display_start, "pm")
    end_half = days * 2 + 1 if event_end >= month_end_excl else half_index(display_end, "am") + 1
    return start_half, end_half


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    issues = []

    for prop in data.get("properties", []):
        events = prop.get("events", [])
        if not events:
            continue

        all_dates = [make_date(e["start"]) for e in events] + [make_date(e["end"]) for e in events]
        overall_start = min(all_dates)
        overall_end = max(all_dates)

        reservation_checkouts = {e["end"] for e in events if e.get("type") != "closed"}

        for month in iter_months(overall_start, overall_end):
            m_start = month_start(month)
            m_end = month_end(month)
            days = m_end.day
            occupancy = {}

            for event in events:
                span = compute_span(event, m_start, m_end, reservation_checkouts)
                if not span:
                    continue
                start_half, end_half = span
                if end_half <= start_half:
                    issues.append(f"{prop['name']} {event['uid']} invalid span")
                    continue

                for half in range(start_half, end_half):
                    if half < 1 or half > days * 2:
                        continue
                    if half in occupancy:
                        issues.append(
                            f"{prop['name']} overlap on {month.strftime('%Y-%m')} half {half}"
                        )
                        break
                    occupancy[half] = event["uid"]

    if issues:
        print("Found issues:")
        for issue in issues:
            print("-", issue)
        return 1

    print("No overlaps detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
