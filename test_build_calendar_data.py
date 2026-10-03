import unittest

from datetime import date

from build_calendar_data import _add_placeholders, _is_buffer_block, _is_preparation_time


class PlaceholderPropertiesTest(unittest.TestCase):
    def test_missing_placeholder_is_added_with_no_events(self):
        properties = [{"name": "59 Oak Lane", "events": [{"uid": "a"}]}]

        result = _add_placeholders(properties, ["18 Coopers Vantage"])

        self.assertEqual(
            [prop["name"] for prop in result],
            ["59 Oak Lane", "18 Coopers Vantage"],
        )
        self.assertEqual(result[1]["events"], [])
        self.assertEqual(properties, [{"name": "59 Oak Lane", "events": [{"uid": "a"}]}])

    def test_placeholder_does_not_replace_a_live_feed(self):
        properties = [{"name": "18 Coopers Vantage", "events": [{"uid": "a"}]}]

        result = _add_placeholders(properties, ["18 Coopers Vantage"])

        self.assertEqual(result, properties)


class PreparationTimeTest(unittest.TestCase):
    def test_plain_and_masked_preparation_time_are_buffers(self):
        self.assertTrue(_is_preparation_time("Preparation Time"))
        self.assertTrue(_is_preparation_time("P********** T***"))

    def test_guest_stays_and_owner_blocks_are_not_buffers(self):
        self.assertFalse(_is_preparation_time("Closed Period"))
        self.assertFalse(_is_preparation_time("Not Available"))
        self.assertFalse(_is_preparation_time("J*** S****"))
        self.assertFalse(_is_preparation_time("P******* T**"))


class MinimumStayTest(unittest.TestCase):
    def test_one_night_booking_is_a_buffer(self):
        self.assertTrue(_is_buffer_block("Not Available", date(2026, 9, 15), date(2026, 9, 16)))
        self.assertTrue(_is_buffer_block("J*** S****", date(2026, 10, 4), date(2026, 10, 5)))

    def test_two_night_stay_and_one_night_owner_block_stay(self):
        self.assertFalse(_is_buffer_block("J*** S****", date(2026, 10, 2), date(2026, 10, 4)))
        self.assertFalse(_is_buffer_block("Closed Period", date(2026, 4, 12), date(2026, 4, 13)))


if __name__ == "__main__":
    unittest.main()
