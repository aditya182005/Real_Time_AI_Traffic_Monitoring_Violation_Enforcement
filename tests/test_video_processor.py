import sqlite3

from tests.db_helpers import db_connect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

cv2 = None
try:
    import cv2
except ImportError:  # pragma: no cover
    pass

from app.violation import violation_logger as vl


class FakeDetector:
    def detect(self, frame):
        return []


class ScriptedTracker:
    """Stands in for VehicleTracker: one car moving down the frame.

    The first frames report no vehicles at all, which used to crash the
    processor because the real tracker returned a plain list in that case.
    """

    def __init__(self, bottoms):
        self.bottoms = bottoms
        self.frame = 0

    def update(self, detections):
        bottom = self.bottoms[self.frame]
        self.frame += 1

        if bottom is None:
            return SimpleNamespace(
                xyxy=np.empty((0, 4)),
                tracker_id=np.empty((0,), dtype=int),
                class_id=np.empty((0,), dtype=int),
            )

        return SimpleNamespace(
            xyxy=np.array([[40.0, bottom - 40, 100.0, float(bottom)]]),
            tracker_id=np.array([5]),
            class_id=np.array([2]),
        )


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class VideoProcessorTests(unittest.TestCase):

    BOTTOMS = [None, None, 100, 140, 180, 220, 260, 300, 340]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "test.db"

        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.video = self.dir / "in.mp4"
        writer = cv2.VideoWriter(
            str(self.video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 400)
        )
        if not writer.isOpened():
            self.skipTest("this OpenCV build cannot write mp4v video")
        for _ in self.BOTTOMS:
            writer.write(np.zeros((400, 160, 3), dtype=np.uint8))
        writer.release()

    def run_pipeline(self, signal_state):
        from app.video_processor import TrafficVideoProcessor

        processor = TrafficVideoProcessor(
            detector=FakeDetector(),
            tracker=ScriptedTracker(self.BOTTOMS),
            stop_line_y=250,
            signal_state=signal_state,
            evidence_dir=self.dir / "evidence",
        )
        # The output folder does not exist yet: it must be created.
        out = self.dir / "nested" / "out.mp4"
        processor.process(self.video, out, show=False)
        return out

    def records(self):
        if not self.db.exists():
            return []
        with db_connect(self.db) as conn:
            return conn.execute(
                "SELECT track_id, violation_type, signal_state, "
                "evidence_path FROM violation_records"
            ).fetchall()

    def test_red_light_crossing_is_logged_with_evidence(self):
        out = self.run_pipeline("RED")

        self.assertTrue(out.exists() and out.stat().st_size > 0)

        records = self.records()
        self.assertEqual(len(records), 1)

        track_id, kind, signal, evidence = records[0]
        self.assertEqual((track_id, kind, signal), (5, "red_light", "RED"))
        self.assertTrue(evidence and Path(evidence).is_file())

    def test_no_violation_on_green(self):
        self.run_pipeline("GREEN")
        self.assertEqual(self.records(), [])


if __name__ == "__main__":
    unittest.main()
