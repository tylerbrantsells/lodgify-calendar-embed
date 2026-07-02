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
