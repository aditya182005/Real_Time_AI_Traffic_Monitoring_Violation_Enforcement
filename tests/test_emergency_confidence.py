import unittest
from unittest import mock

from app.detection import emergency_detector as ed


class ConfidenceTests(unittest.TestCase):
    def check(self, value, expected):
        with mock.patch.dict("os.environ", {"EMERGENCY_CONFIDENCE": value}):
            self.assertEqual(ed.configured_confidence(), expected)

    def test_default_when_unset_or_invalid(self):
        self.check("", ed.DEFAULT_CONFIDENCE)
        self.check("high", ed.DEFAULT_CONFIDENCE)

    def test_value_is_used_and_clamped(self):
        self.check("0.85", 0.85)
        self.check("5", 0.99)
        self.check("0", 0.05)


if __name__ == "__main__":
    unittest.main()
