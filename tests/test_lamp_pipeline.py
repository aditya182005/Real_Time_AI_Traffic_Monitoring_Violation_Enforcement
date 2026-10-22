import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from app.violation import violation_logger as vl
from app.violation.lamp import LampSignal
from tests.db_helpers import db_connect
from tests.test_video_processor import BOTTOMS_FOR_LAMP, FakeDetector, ScriptedTracker


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class LampPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"
        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def video(self, colour):
        path = self.dir / "lamp.mp4"
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 400))

        if not writer.isOpened():
            self.skipTest("this OpenCV build cannot write mp4v video")

        for _ in BOTTOMS_FOR_LAMP:
            frame = np.zeros((400, 160, 3), np.uint8)
            cv2.circle(frame, (135, 30), 12, colour, -1)
            writer.write(frame)

        writer.release()

        return path

    def run_with_lamp(self, colour):
        from app.video_processor import TrafficVideoProcessor

        processor = TrafficVideoProcessor(
            detector=FakeDetector(),
            tracker=ScriptedTracker(BOTTOMS_FOR_LAMP),
            stop_line_y=250,
            signal=LampSignal((60, 0, 100, 25)),
            evidence_dir=self.dir / "evidence",
        )
        processor.process(self.video(colour), self.dir / "out.mp4", show=False)

        with db_connect(self.db) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='violation_records'"
            ).fetchone()

            return [] if not exists else conn.execute(
                "SELECT violation_type, signal_state FROM violation_records"
            ).fetchall()

    def test_red_lamp_makes_a_crossing_a_violation(self):
        self.assertEqual(self.run_with_lamp((0, 0, 255)),
                         [("red_light", "RED")])

    def test_green_lamp_does_not(self):
        self.assertEqual(self.run_with_lamp((0, 200, 0)), [])


if __name__ == "__main__":
    unittest.main()
