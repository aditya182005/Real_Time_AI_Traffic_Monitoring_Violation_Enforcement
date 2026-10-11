import unittest

from app.violation.speed_estimator import SpeedEstimator


def drive(estimator, track_id, start_y, step, frames, fps=10, x=100):
    for frame in range(1, frames + 1):
        speed = estimator.update(
            track_id, x, start_y + step * (frame - 1), frame, fps
        )

        if speed is not None:
            return speed

    return None


class SpeedEstimatorTests(unittest.TestCase):

    def test_known_speed(self):
        # 10 px/frame at 10 fps; the 100 px between the lines is 10 m, so it
        # takes 1 s: 10 m/s = 36 km/h.
        estimator = SpeedEstimator(150, 250, distance_m=10)

        self.assertAlmostEqual(drive(estimator, 1, 100, 10, 30), 36.0)

    def test_slower_vehicle_measures_lower(self):
        estimator = SpeedEstimator(150, 250, distance_m=10)

        self.assertAlmostEqual(drive(estimator, 1, 100, 4, 60), 14.4)

    def test_each_vehicle_is_measured_once(self):
        estimator = SpeedEstimator(150, 250, distance_m=10)
        results = [
            estimator.update(1, 100, 100 + 10 * f, f + 1, 10)
            for f in range(40)
        ]

        self.assertEqual(len([r for r in results if r is not None]), 1)

    def test_works_in_both_directions(self):
        estimator = SpeedEstimator(150, 250, distance_m=10)

        self.assertAlmostEqual(drive(estimator, 1, 320, -10, 30), 36.0)

    def test_vehicle_that_never_reaches_line_b_has_no_speed(self):
        estimator = SpeedEstimator(150, 250, distance_m=10)

        self.assertIsNone(drive(estimator, 1, 100, 10, 12))  # stops at ~210

    def test_lane_filter_skips_other_lanes(self):
        estimator = SpeedEstimator(150, 250, 10, x_min=0, x_max=100)

        self.assertIsNone(drive(estimator, 1, 100, 10, 30, x=250))

    def test_invalid_setup_is_rejected(self):
        with self.assertRaises(ValueError):
            SpeedEstimator(150, 250, distance_m=0)

        with self.assertRaises(ValueError):
            SpeedEstimator(200, 200, distance_m=10)


if __name__ == "__main__":
    unittest.main()
