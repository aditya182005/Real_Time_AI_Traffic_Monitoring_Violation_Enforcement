import unittest

from app.violation.wrong_way import WrongWayDetector


def drive(detector, track_id, start_y, step, frames, x=100):
    """Move a vehicle `step` px per frame; return the frame it was flagged."""

    for frame in range(frames):
        if detector.update(track_id, x, start_y + step * frame):
            return frame

    return None


class WrongWayTests(unittest.TestCase):

    def test_vehicle_moving_against_traffic_is_flagged_once(self):
        detector = WrongWayDetector(expected="down")

        flagged = drive(detector, 1, 300, -8, 30)

        self.assertIsNotNone(flagged)
        # Already reported: never flagged a second time.
        self.assertFalse(detector.update(1, 100, 0))

    def test_vehicle_moving_with_traffic_is_not_flagged(self):
        self.assertIsNone(drive(WrongWayDetector("down"), 1, 100, 8, 30))

    def test_direction_up_reverses_the_rule(self):
        self.assertIsNone(drive(WrongWayDetector("up"), 1, 300, -8, 30))
        self.assertIsNotNone(drive(WrongWayDetector("up"), 2, 100, 8, 30))

    def test_jitter_and_stopped_vehicles_are_ignored(self):
        detector = WrongWayDetector("down")

        # Wobbles +-2 px around one spot, e.g. a car waiting in a queue.
        flagged = any(
            detector.update(1, 100, 200 + (2 if i % 2 else -2))
            for i in range(40)
        )

        self.assertFalse(flagged)

    def test_short_reversal_is_ignored(self):
        # 20 px backwards is under the 40 px minimum travel.
        self.assertIsNone(drive(WrongWayDetector("down"), 1, 300, -2, 10))

    def test_lane_restriction_ignores_the_oncoming_carriageway(self):
        detector = WrongWayDetector("down", x_min=0, x_max=150)

        # Moves "up" but in the right-hand carriageway (x=250): legal there.
        self.assertIsNone(drive(detector, 1, 300, -8, 30, x=250))
        # Same movement inside the checked lane is flagged.
        self.assertIsNotNone(drive(detector, 2, 300, -8, 30, x=100))

    def test_invalid_direction_is_rejected(self):
        with self.assertRaises(ValueError):
            WrongWayDetector("sideways")


if __name__ == "__main__":
    unittest.main()
