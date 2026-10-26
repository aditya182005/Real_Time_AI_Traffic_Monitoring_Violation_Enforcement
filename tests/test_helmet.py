import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from app.detection.helmet_detector import normalise
from app.violation import helmet, violation_logger as vl
from tests.db_helpers import db_connect

BIKE = (100, 200, 160, 300)          # 60 wide, 100 tall
RIDER_HEAD = (115, 150, 145, 185)    # above the bike, inside its width


def head(name, box=RIDER_HEAD, conf=0.9):
    return {"class_name": name, "confidence": conf, "bbox": box}


class MatchingTests(unittest.TestCase):
    def test_head_above_the_bike_belongs_to_it(self):
        self.assertTrue(helmet.head_belongs_to(RIDER_HEAD, BIKE))
        self.assertTrue(helmet.head_belongs_to((115, 100, 145, 130), BIKE))

    def test_other_heads_do_not(self):
        self.assertFalse(helmet.head_belongs_to((300, 150, 330, 185), BIKE))  # beside
        self.assertFalse(helmet.head_belongs_to((115, 0, 145, 30), BIKE))     # far above
        self.assertFalse(helmet.head_belongs_to((115, 340, 145, 370), BIKE))  # below

    def test_class_names(self):
        for name, expected in (("helmet", "helmet"), ("With Helmet", "helmet"),
                               ("no_helmet", "no_helmet"),
                               ("Without Helmet", "no_helmet"),
                               ("no helmet", "no_helmet"), ("head", "no_helmet"),
                               ("person", None), ("motorbike", None)):
            self.assertEqual(normalise(name), expected, name)


class VotingTests(unittest.TestCase):
    def test_needs_several_frames_and_fires_once(self):
        checker = helmet.HelmetChecker(confirm=3)
        results = [checker.update(1, BIKE, [head("no_helmet")])
                   for _ in range(5)]

        self.assertEqual(results, [False, False, True, False, False])

    def test_helmet_frames_outvote_a_few_misses(self):
        checker = helmet.HelmetChecker(confirm=2)
        frames = [head("helmet")] * 5 + [head("no_helmet")] * 2

        self.assertFalse(any(checker.update(1, BIKE, [h]) for h in frames))

    def test_low_confidence_and_other_riders_are_ignored(self):
        checker = helmet.HelmetChecker(confirm=1)

        self.assertFalse(checker.update(1, BIKE, [head("no_helmet", conf=0.2)]))
        self.assertFalse(checker.update(
            1, BIKE, [head("no_helmet", (400, 150, 430, 185))]))
        self.assertTrue(checker.update(1, BIKE, [head("no_helmet")]))

    def test_tracks_are_independent(self):
        checker = helmet.HelmetChecker(confirm=1)

        self.assertTrue(checker.update(1, BIKE, [head("no_helmet")]))
        self.assertTrue(checker.update(2, BIKE, [head("no_helmet")]))


class FakeHelmetDetector:
    def __init__(self, heads):
        self.heads = heads

    def detect(self, frame):
        return self.heads


class BikeTracker:
    def update(self, detections):
        return SimpleNamespace(
            xyxy=np.array([[100.0, 200.0, 160.0, 300.0]]),
            tracker_id=np.array([9]), class_id=np.array([3]))


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class PipelineTests(unittest.TestCase):
    def run_with(self, heads):
        from app.video_processor import TrafficVideoProcessor

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        db = d / "t.db"
        patcher = mock.patch.object(vl, "DB_PATH", db)
        patcher.start()
        self.addCleanup(patcher.stop)
        video = d / "in.mp4"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"),
                                 10, (320, 400))

        if not writer.isOpened():
            self.skipTest("cannot write mp4v")

        for _ in range(6):
            writer.write(np.zeros((400, 320, 3), np.uint8))

        writer.release()
        processor = TrafficVideoProcessor(
            detector=mock.Mock(detect=lambda f: []), tracker=BikeTracker(),
            signal_state="GREEN", evidence_dir=d / "ev",
            helmet_detector=FakeHelmetDetector(heads))
        summary = processor.process(video, d / "out.mp4", show=False)

        if not db.exists():
            return summary, []

        with db_connect(db) as conn:
            return summary, conn.execute(
                "SELECT violation_type, fine_amount FROM violation_records"
            ).fetchall()

    def test_rider_without_helmet_is_logged_once_with_a_fine(self):
        summary, rows = self.run_with([head("no_helmet")])

        self.assertEqual([tuple(r) for r in rows], [("no_helmet", 1000)])
        self.assertEqual(len(summary.violations_of("no_helmet")), 1)

    def test_helmeted_rider_is_not_flagged(self):
        _, rows = self.run_with([head("helmet")])

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
