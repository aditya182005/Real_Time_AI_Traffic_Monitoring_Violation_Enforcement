import unittest

from app.violation.red_light import RedLightDetector


class RedLightDetectorTests(unittest.TestCase):

    def setUp(self):
        self.detector = RedLightDetector(stop_line_y=300)

    def test_crossing_on_red_is_flagged_once(self):
        self.assertFalse(self.detector.check(1, 250, "RED"))
        self.assertTrue(self.detector.check(1, 320, "RED"))
        # Same vehicle keeps moving: must not be reported again.
        self.assertFalse(self.detector.check(1, 350, "RED"))

    def test_crossing_on_green_is_not_flagged(self):
        self.assertFalse(self.detector.check(2, 250, "GREEN"))
        self.assertFalse(self.detector.check(2, 320, "GREEN"))

    def test_signal_turning_green_before_crossing(self):
        self.assertFalse(self.detector.check(3, 250, "RED"))
        self.assertFalse(self.detector.check(3, 320, "GREEN"))

    def test_vehicle_first_seen_past_the_line_is_not_flagged(self):
        self.assertFalse(self.detector.check(4, 400, "RED"))
        self.assertFalse(self.detector.check(4, 420, "RED"))

    def test_missing_track_id_is_ignored(self):
        self.assertFalse(self.detector.check(None, 320, "RED"))

    def test_check_has_no_database_side_effects(self):
        # Logging is the caller's job now; check() must stay pure.
        import app.violation.red_light as module
        self.assertFalse(hasattr(module, "log_violation"))


if __name__ == "__main__":
    unittest.main()
