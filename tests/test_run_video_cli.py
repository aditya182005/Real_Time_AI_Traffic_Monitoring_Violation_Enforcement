import contextlib
import io
import sqlite3
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

import run_video
from app.violation import violation_logger as vl


class FakeDetector:
    def detect(self, frame, conf=None):
        return []


class CarMovingDown:
    """One car (track 5) whose bottom edge goes from 100 to 340 px."""

    def __init__(self):
        self.frame = 0

    def update(self, detections):
        bottom = 100 + 30 * self.frame
        self.frame += 1

        return SimpleNamespace(
            xyxy=np.array([[40.0, bottom - 40, 100.0, float(bottom)]]),
            tracker_id=np.array([5]),
            class_id=np.array([2]),
        )


class ArgumentTests(unittest.TestCase):

    def parse(self, *argv):
        return run_video.build_parser().parse_args(list(argv))

    def test_defaults_run_only_the_red_light_check(self):
        settings = run_video.settings_from_args(self.parse())

        self.assertEqual(settings.signal_mode, "red")
        self.assertFalse(settings.check_speed)
        self.assertFalse(settings.check_wrong_way)
        self.assertFalse(settings.check_collisions)
        self.assertFalse(settings.use_emergency)
        self.assertTrue(settings.save_to_db)

    def test_options_map_onto_settings(self):
        settings = run_video.settings_from_args(self.parse(
            "--signal", "CYCLE", "--speed", "--distance-m", "12",
            "--speed-limit", "50", "--wrong-way", "--direction", "up",
            "--lane-from-pct", "10", "--lane-to-pct", "60",
            "--collisions", "--no-save", "--camera-id", "NH-4",
        ))

        self.assertEqual(settings.signal_mode, "cycle")
        self.assertTrue(settings.check_speed)
        self.assertEqual((settings.speed_distance_m, settings.speed_limit_kmh),
                         (12, 50))
        self.assertEqual(settings.expected_direction, "up")
        self.assertEqual((settings.lane_from_pct, settings.lane_to_pct),
                         (10, 60))
        self.assertTrue(settings.check_collisions)
        self.assertFalse(settings.save_to_db)
        self.assertEqual(settings.camera_id, "NH-4")


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class RunTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

        # Keep evidence out of the real outputs/ folder.
        patcher = mock.patch.object(run_video, "ROOT", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.video = self.dir / "in.mp4"
        writer = cv2.VideoWriter(
            str(self.video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 400))

        if not writer.isOpened():
            self.skipTest("this OpenCV build cannot write mp4v video")

        for _ in range(9):
            writer.write(np.zeros((400, 160, 3), np.uint8))

        writer.release()

    def run_cli(self, *extra):
        argv = ["--input", str(self.video), "--output",
                str(self.dir / "out.mp4"), "--no-display", *extra]

        with contextlib.redirect_stdout(io.StringIO()):
            return run_video.main(
                argv, detector=FakeDetector(), tracker=CarMovingDown())

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(
                "SELECT event_key, camera_id, source "
                "FROM violation_records").fetchall()

    def test_red_light_run_is_saved_with_camera_and_source(self):
        summary = self.run_cli("--camera-id", "NH-4")

        self.assertEqual(len(summary.violations), 1)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:], ("NH-4", "in.mp4"))

    def test_running_the_same_video_twice_saves_both_runs(self):
        # Regression: without a per-run ID the second run produced the same
        # event key and the database silently discarded the violation.
        self.run_cli()
        self.run_cli()

        keys = [row[0] for row in self.rows()]
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(set(keys)), 2)

    def test_no_save_leaves_the_database_alone(self):
        summary = self.run_cli("--no-save")

        self.assertEqual(len(summary.violations), 1)
        self.assertFalse(self.db.exists())

    def test_green_signal_finds_no_red_light_violation(self):
        summary = self.run_cli("--signal", "green")

        self.assertEqual(summary.violations, [])

    def test_bad_settings_are_rejected_before_any_work(self):
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit):
            run_video.main(["--speed", "--line-a-pct", "50",
                            "--line-b-pct", "50"])

        self.assertIn("Move speed line A and B apart", stderr.getvalue())

    def test_alerts_need_collision_checking(self):
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit):
            run_video.main(["--send-alerts"])

        self.assertIn("--send-alerts needs --collisions",
                      stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
