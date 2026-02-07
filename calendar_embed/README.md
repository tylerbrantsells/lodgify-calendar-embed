## Calendar Embed (Design Spark Properties)

### Pinned version
A snapshot of the previous working version is stored in:
`calendar_embed_pinned_2026-02-06/`

### Core model
All-day iCal events are rendered on a **half‑day grid** (AM/PM) over the active **view range**:
- **Reservation**: start **PM**, end **AM + 1** (so checkout morning is included).
- **Closed Period**: start **AM**, end **AM** (exclusive).
- If a Closed Period starts on a reservation checkout date, it starts **PM**.
- Cross‑range spans clamp to the end of the current view range.

### Important pitfall (fixed)
When the view range spans multiple months, **half‑day indices must be computed relative to the
range start**, not the day-of-month. Using day-of-month causes:
- Reservations ending early (cut off at month boundaries).
- Missing or misaligned blocks (ex: 59 Oak manual block not visible).

Fix: compute `halfIndex` from `(dateObj - rangeStart)` in days.

### Live iCal Sync (Hourly)
Set `ICS_URLS_JSON` to fetch live Lodgify iCal feeds. Supported formats:

**Mapping (recommended):**
```json
{
  "59 Oak Lane": "https://www.lodgify.com/xxxx.ics",
  "333 Dobie": "https://www.lodgify.com/yyyy.ics"
}
```

Optional env vars:
- `ICS_REQUEST_TIMEOUT` (default `20`)
- `ICS_USER_AGENT` (default `LodgifyCalendarSync/1.0`)
- `ICS_INSECURE_SSL` (default `false`)
- `CALENDAR_MIN_DATE` (default `2026-01-01`) — ignore any events ending before this date.

### Manual block overrides
Manual blocks remove any overlapping events for the property before inserting the block.
Used to keep **59 Oak Lane** closed until **2026‑09‑07**.

### Auto‑refresh
The embedded view auto‑refreshes every hour.

### View behavior
The UI renders a rolling **180‑day** timeline with horizontal scroll.
Prev/Next shifts the window by **30 days**.

### Alerts on sync failure
If any iCal feed fails to fetch or is empty, an email alert is sent.

Required env vars:
- `SMTP_HOST`
- `SMTP_PORT` (default `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`

Optional:
- `ALERT_EMAIL_TO` (default `hello@designspark.properties`)
- `ALERT_EMAIL_FROM` (default `SMTP_USERNAME`)
- `SMTP_USE_TLS` (default `true`)

### Validation
Run to detect overlap issues in the generated data:
```bash
python3 validate_calendar_data.py
```

### Files
- `calendar_embed/index.html`
- `calendar_embed/styles.css`
- `calendar_embed/app.js`
- `calendar_embed/STYLE_GUIDE.md`
- `build_calendar_data.py`
- `validate_calendar_data.py`
