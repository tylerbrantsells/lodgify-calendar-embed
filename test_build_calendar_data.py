import unittest

from build_calendar_data import _add_placeholders, _is_preparation_time


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


if __name__ == "__main__":
    unittest.main()
