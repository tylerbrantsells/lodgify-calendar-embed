# Calendar Deploy Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the public calendar embed (calendar.designsparkproperties.com) self-heal after GitHub Pages deploy failures, independently alarm when the live site goes stale, and defuse the broken ACME certificate before it expires 2026-07-09.

**Architecture:** Three independent layers. (1) A rescue workflow in `tylerbrantsells/lodgify-calendar-embed` re-runs failed Pages deploys with an attempt cap. (2) A stdlib-only Python staleness checker in `DSP-Cleaner-Calendar` runs from the existing hourly launchd job and emails via the existing SMTP alert config when the live site's `Last-Modified` exceeds 3 hours. (3) A one-time cert re-provision after the Cloudflare record is flipped to DNS-only.

**Tech Stack:** GitHub Actions (`workflow_run` trigger, `gh api`), Python 3.12 stdlib + `requests` (already a dependency), launchd runner (`run-cleaner-calendar.sh`), GitHub Pages API.

**Background (verified 2026-07-02):** Deploy failures 16:55–22:12 UTC were caused by a confirmed GitHub Pages incident (opened 16:54, resolved 18:25, residual degradation after). A manual re-run at 23:28 UTC succeeded; site is currently fresh. Separately, `https_certificate.state == "bad_authz"` because the domain is Cloudflare-proxied (ACME challenge can't reach GitHub); origin cert expires 2026-07-09.

---

### Task 1: Rescue workflow in lodgify-calendar-embed (G001)

**Files:**
- Create (remote repo, via scratchpad clone): `.github/workflows/deploy-rescue.yml`

- [ ] **Step 1: Clone the embed repo to scratchpad**

```bash
gh repo clone tylerbrantsells/lodgify-calendar-embed \
  /private/tmp/claude-501/.../scratchpad/lodgify-calendar-embed
```

- [ ] **Step 2: Write the workflow**

```yaml
name: Deploy rescue

# Re-runs the Pages deploy when it fails (e.g. transient GitHub Pages
# degradation like the 2026-07-02 incident). workflow_run fires again on
# each completed attempt, so run_attempt caps total retries at 3.

on:
  workflow_run:
    workflows: ["Deploy calendar to GitHub Pages"]
    types: [completed]

permissions:
  actions: write

jobs:
  rerun-failed-deploy:
    if: >-
      github.event.workflow_run.conclusion == 'failure' &&
      github.event.workflow_run.run_attempt < 4
    runs-on: ubuntu-latest
    steps:
      - name: Wait 5 minutes (let transient outages clear)
        run: sleep 300
      - name: Re-run failed jobs of the deploy run
        env:
          GH_TOKEN: ${{ github.token }}
        run: >-
          gh api -X POST
          "repos/${{ github.repository }}/actions/runs/${{ github.event.workflow_run.id }}/rerun-failed-jobs"
```

- [ ] **Step 3: Validate YAML parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/deploy-rescue.yml'))" `
Expected: exit 0, no output. (Fallback if PyYAML missing: `ruby -ryaml -e ...` or skip to Step 5's registration check, which is the real gate.)

- [ ] **Step 4: Commit and push**

```bash
git add .github/workflows/deploy-rescue.yml
git commit -m "ci: auto-rerun failed Pages deploys (max 3 attempts, 5m backoff)"
git push
```

- [ ] **Step 5: Verify GitHub registered the workflow**

Run: `gh workflow list --repo tylerbrantsells/lodgify-calendar-embed`
Expected: "Deploy rescue" appears as active.

### Task 2: Staleness alarm in DSP-Cleaner-Calendar (G002)

**Files:**
- Create: `check_embed_freshness.py`
- Create: `test_check_embed_freshness.py`
- Modify: `run-cleaner-calendar.sh` (append one non-fatal step)
- Modify: `.gitignore` (state file)

- [ ] **Step 1: Write failing unit tests (stdlib unittest — repo has no pytest)**

```python
#!/usr/bin/env python3
import unittest
from datetime import datetime, timezone, timedelta

from check_embed_freshness import is_stale, should_alert

NOW = datetime(2026, 7, 2, 23, 0, 0, tzinfo=timezone.utc)


class IsStaleTests(unittest.TestCase):
    def test_fresh_header_is_not_stale(self):
        header = "Thu, 02 Jul 2026 22:30:00 GMT"
        self.assertFalse(is_stale(header, NOW))

    def test_old_header_is_stale(self):
        header = "Thu, 02 Jul 2026 14:22:53 GMT"  # the real 9h-stale case
        self.assertTrue(is_stale(header, NOW))

    def test_exactly_at_threshold_is_not_stale(self):
        header = "Thu, 02 Jul 2026 20:00:00 GMT"  # exactly 3h
        self.assertFalse(is_stale(header, NOW))

    def test_unparseable_header_counts_as_stale(self):
        self.assertTrue(is_stale("not-a-date", NOW))


class ShouldAlertTests(unittest.TestCase):
    def test_no_previous_alert_allows_alert(self):
        self.assertTrue(should_alert({}, NOW))

    def test_recent_alert_suppressed_by_cooldown(self):
        state = {"last_alert_utc": (NOW - timedelta(hours=2)).isoformat()}
        self.assertFalse(should_alert(state, NOW))

    def test_old_alert_allows_realert(self):
        state = {"last_alert_utc": (NOW - timedelta(hours=7)).isoformat()}
        self.assertTrue(should_alert(state, NOW))

    def test_corrupt_state_allows_alert(self):
        self.assertTrue(should_alert({"last_alert_utc": "garbage"}, NOW))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests, verify they FAIL (module doesn't exist)**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 test_check_embed_freshness.py`
Expected: `ModuleNotFoundError: No module named 'check_embed_freshness'`

- [ ] **Step 3: Implement check_embed_freshness.py**

```python
#!/usr/bin/env python3
"""Alert if the PUBLIC calendar embed has gone stale.

The embed at calendar.designsparkproperties.com is redeployed hourly by
GitHub Actions (every "Lodgify iCal Sync" completion triggers a Pages
deploy, changes or not), so its Last-Modified should never be more than
~1h old. If it exceeds STALE_AFTER_HOURS, deploys are failing (Pages
outage, dead cron, disabled workflow...) and an alert email goes out
using the same SMTP_*/ALERT_* .env config as the sync alerts. A state
file enforces a re-alert cooldown so an ongoing outage doesn't email
every hour. Never exits non-zero in a way that matters: the runner
invokes it non-fatally, and a monitoring failure must not block the
Notion sync.
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
STALE_AFTER_HOURS = 3
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
```

- [ ] **Step 4: Run tests, verify PASS**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 test_check_embed_freshness.py`
Expected: `Ran 8 tests ... OK`

- [ ] **Step 5: Live smoke test against the real site**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 check_embed_freshness.py`
Expected: `freshness: OK (Last-Modified: ...)`, exit 0 (site was redeployed 23:28 UTC).

- [ ] **Step 6: Wire into the launchd runner (non-fatal — set -eu is active)**

Append to `run-cleaner-calendar.sh` after the notion sync line:

```bash
# Independent watchdog: alert if the PUBLIC embed stops redeploying
# (Pages outage, dead cron...). Non-fatal — monitoring must never
# block or fail the sync above.
"$PYTHON" check_embed_freshness.py || echo "freshness check reported stale/unreachable (alert handled in-script)" >&2
```

- [ ] **Step 7: Gitignore the state file**

Append `.freshness-alert-state.json` to `.gitignore`.

- [ ] **Step 8: Full runner smoke test**

Run: `zsh run-cleaner-calendar.sh`
Expected: refresh_ics + notion sync run as before, then `freshness: OK (...)`, exit 0.

- [ ] **Step 9: Commit**

```bash
git add check_embed_freshness.py test_check_embed_freshness.py run-cleaner-calendar.sh .gitignore
git commit -m "feat: embed staleness watchdog — alert when Pages deploys silently fail"
git push
```

### Task 3: Defuse the bad_authz certificate (G003) — blocked on Cloudflare flip

**Files:** none locally — GitHub Pages API + Cloudflare dashboard.

- [ ] **Step 1 (TYLER, manual):** In Cloudflare DNS for `designsparkproperties.com`, edit the `calendar` record: type **CNAME**, target **tylerbrantsells.github.io**, proxy status **DNS only (grey cloud)**.

- [ ] **Step 2: Verify DNS now bypasses Cloudflare**

Run: `dig +short calendar.designsparkproperties.com CNAME`
Expected: `tylerbrantsells.github.io.` (and A lookups return 185.199.x.x, not 104.21.x/172.67.x).

- [ ] **Step 3: Remove and re-add the custom domain to restart ACME**

```bash
gh api -X PUT repos/tylerbrantsells/lodgify-calendar-embed/pages -f cname=""     # remove
sleep 30
gh api -X PUT repos/tylerbrantsells/lodgify-calendar-embed/pages -f cname="calendar.designsparkproperties.com"
```

- [ ] **Step 4: Poll until the cert is healthy**

Run (repeat over ~15–60 min): `gh api repos/tylerbrantsells/lodgify-calendar-embed/pages --jq '.https_certificate.state'`
Expected: progresses `new`/`authorization_created` → `approved`/`issued`. Then re-enable enforcement if it dropped: `gh api -X PUT repos/tylerbrantsells/lodgify-calendar-embed/pages -F https_enforced=true`

- [ ] **Step 5: End-to-end check**

Run: `curl -sI https://calendar.designsparkproperties.com/ | head -3` and `echo QUIT | openssl s_client -connect calendar.designsparkproperties.com:443 2>&1 | grep -E "issuer|Verify"`
Expected: HTTP 200, valid cert with fresh expiry (not 2026-07-09).

## Risks
- **Rescue loop:** `run_attempt < 4` cap prevents infinite reruns; `workflow_run` re-fires per attempt by design.
- **Cert window (Task 3 Step 3):** brief 404/cert-warning window during domain re-add; minutes at most, calendar embed traffic tolerant.
- **Cooldown state corruption:** treated as "alert allowed" (fail-open) — tested.

## Complexity: LOW (Tasks 1–2 ~45 min; Task 3 blocked on manual Cloudflare flip, then ~15 min)
