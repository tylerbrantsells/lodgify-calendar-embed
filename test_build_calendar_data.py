import unittest

from build_calendar_data import _add_placeholders


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


if __name__ == "__main__":
    unittest.main()
