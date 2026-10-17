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


class MissingByteTrackTests(unittest.TestCase):
    """supervision 0.31 removed ByteTrack; the failure must be understandable."""

    def test_clear_error_when_byte_track_is_missing(self):
        import importlib
        import sys
        import types

        stub = types.SimpleNamespace(Detections=object)
        previous = sys.modules.get("supervision")
        sys.modules["supervision"] = stub
        sys.modules.pop("app.tracking.tracker", None)

        try:
            module = importlib.import_module("app.tracking.tracker")

            with self.assertRaisesRegex(RuntimeError, r"<0\.31"):
                module.VehicleTracker()
        finally:
            sys.modules.pop("app.tracking.tracker", None)

            if previous is None:
                sys.modules.pop("supervision", None)
            else:
                sys.modules["supervision"] = previous


class RequirementsPinTests(unittest.TestCase):

    def test_supervision_is_pinned_below_the_release_without_byte_track(self):
        from pathlib import Path

        text = (Path(__file__).resolve().parents[1]
                / "requirements.txt").read_text()
        line = next(l for l in text.splitlines()
                    if l.startswith("supervision"))

        self.assertIn("<0.31", line)
