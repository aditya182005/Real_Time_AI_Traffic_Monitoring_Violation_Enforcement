import unittest

try:
    import supervision  # noqa: F401
except ImportError:  # pragma: no cover
    supervision = None


@unittest.skipIf(supervision is None, "supervision not installed")
class VehicleTrackerTests(unittest.TestCase):

    def test_empty_frame_returns_detections_not_a_list(self):
        from app.tracking.tracker import VehicleTracker

        tracked = VehicleTracker().update([])

        # Previously a bare list, which made `tracked.xyxy` raise
        # AttributeError in the video processor on any empty frame.
        self.assertEqual(len(tracked.xyxy), 0)

    def test_detection_gets_a_track_id(self):
        from app.tracking.tracker import VehicleTracker

        tracker = VehicleTracker()
        detection = {
            "class_id": 2,
            "class_name": "car",
            "confidence": 0.9,
            "bbox": (10, 10, 60, 60),
        }

        tracked = None
        for _ in range(3):
            tracked = tracker.update([detection])

        self.assertEqual(len(tracked.xyxy), 1)
        self.assertIsNotNone(tracked.tracker_id)


if __name__ == "__main__":
    unittest.main()
