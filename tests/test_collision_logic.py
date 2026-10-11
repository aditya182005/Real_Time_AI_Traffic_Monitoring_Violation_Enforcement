import unittest

from app.violation.collision_logic import CollisionHeuristic, calculate_iou


def box(cx, cy=100, w=40, h=40):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


class IouTests(unittest.TestCase):

    def test_identical_and_disjoint(self):
        self.assertEqual(calculate_iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)
        self.assertEqual(calculate_iou((0, 0, 10, 10), (20, 20, 30, 30)), 0.0)

    def test_half_overlap(self):
        self.assertAlmostEqual(
            calculate_iou((0, 0, 10, 10), (5, 0, 15, 10)), 1 / 3
        )


class CollisionHeuristicTests(unittest.TestCase):

    def run_scenario(self, positions, **kwargs):
        """positions: list of (cx_a, cx_b) per frame. Returns frames alerted."""

        heuristic = CollisionHeuristic(**kwargs)
        alerts = []

        for frame, (a, b) in enumerate(positions, start=1):
            if heuristic.update([(1, box(a)), (2, box(b))]):
                alerts.append(frame)

        return alerts

    def test_head_on_crash_then_both_stop_is_reported_once(self):
        # Approach at 10 px/frame, touch around frame 9, then stop dead.
        approach = [(20 + 10 * f, 220 - 10 * f) for f in range(0, 10)]
        stopped = [approach[-1]] * 8

        alerts = self.run_scenario(approach + stopped)

        self.assertEqual(len(alerts), 1)

    def test_stationary_overlap_in_a_queue_is_ignored(self):
        # Boxes overlap for a long time but nothing ever slowed down.
        alerts = self.run_scenario([(100, 120)] * 30)

        self.assertEqual(alerts, [])

    def test_constant_speed_overlap_is_ignored(self):
        # One vehicle passing another in perspective: overlap, no braking.
        positions = [(100 + 10 * f, 110 + 10 * f) for f in range(30)]

        self.assertEqual(self.run_scenario(positions), [])

    def test_overlap_must_persist(self):
        approach = [(20 + 10 * f, 220 - 10 * f) for f in range(0, 10)]
        # Overlap for only two frames, then the vehicles separate.
        positions = approach + [approach[-1]] + [(400, 0)] * 5

        self.assertEqual(self.run_scenario(positions), [])

    def test_velocity_check_can_be_disabled(self):
        alerts = self.run_scenario(
            [(100, 120)] * 10, require_velocity_drop=False
        )

        self.assertEqual(len(alerts), 1)


if __name__ == "__main__":
    unittest.main()
