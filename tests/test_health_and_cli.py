import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

import numpy as np

cv2 = None
try:
    import cv2
except ImportError:  # pragma: no cover
    pass

import evaluate
import run_video
from app import health, plates
from app.violation import violation_logger as vl
from tests.db_helpers import db_connect
from tests.test_live import ListCapture
from tests.test_plates import FakeReader
from tests.test_run_video_cli import CarMovingDown, FakeDetector


class HealthTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        for target, name, value in ((vl, "DB_PATH", self.db),
                                    (health.paths, "DATA_DIR", self.dir)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def by_name(self, report):
        return {c["name"]: c for c in report["checks"]}

    def test_a_writable_database_is_ok(self):
        self.assertEqual(health.check_database()["status"], "ok")

    def test_an_unwritable_database_fails(self):
        with mock.patch.object(vl, "DB_PATH", self.dir):   # a folder
            self.assertEqual(health.check_database()["status"], "fail")

    def test_low_disk_space_warns(self):
        usage = namedtuple("usage", "total used free")

        with mock.patch.object(health.shutil, "disk_usage",
                               return_value=usage(10**12, 10**12, 10**8)):
            check = health.check_disk()

        self.assertEqual(check["status"], "warn")
        self.assertIn("95 MB", check["detail"])

    def test_alerts_with_no_database_or_table(self):
        self.assertEqual(health.check_alerts()["status"], "ok")
        vl.setup_database()
        self.assertEqual(health.check_alerts()["status"], "ok")

    def test_failing_alerts_warn_but_working_ones_do_not(self):
        vl.setup_database()

        def event(status):
            vl.log_collision_event(1, 2, "x.jpg", alert_status=status)

        event("sent")
        event("sent")
        event("failed: nope")
        self.assertEqual(health.check_alerts()["status"], "ok")

        event("failed: nope")
        event("failed: nope")
        check = health.check_alerts()

        self.assertEqual(check["status"], "warn")
        self.assertIn("3 alert(s) failed", check["detail"])
        self.assertNotIn("nope", check["detail"])

    def test_cameras(self):
        self.assertEqual(health.check_cameras([])["status"], "ok")

        good = {"camera": "A", "state": "running", "connection": "running"}
        bad = {"camera": "B", "state": "running",
               "connection": "reconnecting"}

        self.assertEqual(health.check_cameras([good])["status"], "ok")
        check = health.check_cameras([good, bad])

        self.assertEqual(check["status"], "warn")
        self.assertIn("B", check["detail"])
        self.assertNotIn("A", check["detail"].replace("attention", ""))

    def test_overall_status_is_the_worst_one(self):
        with mock.patch.object(health, "check_twilio", return_value={
                "name": "twilio", "status": "warn", "detail": "x"}):
            self.assertEqual(health.run_checks([])["status"], "warn")

        with mock.patch.object(health, "check_database", return_value={
                "name": "database", "status": "fail", "detail": "x"}):
            self.assertEqual(health.run_checks([])["status"], "fail")

    def test_command_line_exit_codes_and_json(self):
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            code = health.main(["--json"])

        self.assertIn(code, (0,))
        self.assertIn("checks", json.loads(out.getvalue()))

        with mock.patch.object(vl, "DB_PATH", self.dir), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(health.main([]), 1)


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class LiveCommandLineTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        for target, name, value in (
            (vl, "DB_PATH", self.db),
            (run_video, "OUTPUT_DIR", self.dir / "outputs"),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, *argv, **components):
        out = io.StringIO()
        components.setdefault("detector", FakeDetector())
        components.setdefault("tracker", CarMovingDown())

        with contextlib.redirect_stdout(out):
            summary = run_video.main(["--no-display", *argv], **components)

        return summary, out.getvalue()

    def test_a_stream_is_analyzed_and_saved_as_live(self):
        seen = []

        def factory(source):
            seen.append(source)

            return ListCapture()

        summary, output = self.run_cli(
            "--input", "rtsp://cam.local/stream", "--camera-id", "GATE",
            capture_factory=factory)

        self.assertEqual(seen, ["rtsp://cam.local/stream"])
        self.assertEqual(summary.frames, 9)
        self.assertEqual(len(summary.violations), 1)
        self.assertIsNone(summary.output_path)
        self.assertNotIn("Annotated video", output)

        with db_connect(self.db) as conn:
            rows = conn.execute(
                "SELECT source, camera_id FROM violation_records").fetchall()

        self.assertEqual(rows, [("live:GATE", "GATE")])

    def test_a_webcam_number_is_a_live_source(self):
        seen = []
        self.run_cli("--input", "0", "--no-save",
                     capture_factory=lambda s: seen.append(s) or ListCapture())

        self.assertEqual(seen, [0])

    def test_the_camera_password_is_never_printed(self):
        _, output = self.run_cli(
            "--input", "rtsp://admin:hunter2@10.0.0.9/s", "--no-save",
            capture_factory=lambda s: ListCapture())

        self.assertNotIn("hunter2", output)
        self.assertIn("10.0.0.9", output)

    def test_bad_live_options_are_refused(self):
        for argv, message in (
            (["--input", "ftp://x/y"], "must start with"),
            (["--input", "rtsp://x/y", "--output", "out.mp4"],
             "not used for live"),
        ):
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr), \
                    self.assertRaises(SystemExit):
                run_video.main(["--no-display", *argv])

            self.assertIn(message, stderr.getvalue())

    def test_a_camera_that_never_answers_exits_with_a_message(self):
        class Silent(ListCapture):
            def __init__(self):
                super().__init__()
                self.last_error = "could not open the camera"

            def wait_for_first_frame(self, timeout=15.0):
                return False

        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit) as caught:
            self.run_cli("--input", "rtsp://x/y",
                         capture_factory=lambda s: Silent())

        self.assertEqual(caught.exception.code, 1)
        self.assertIn("could not open the camera", stderr.getvalue())

    def test_max_seconds_ends_an_endless_stream(self):
        class Endless(ListCapture):
            def read(self):
                import time
                time.sleep(0.005)

                return True, np.zeros((400, 160, 3), np.uint8)

        summary, _ = self.run_cli(
            "--input", "rtsp://x/y", "--max-seconds", "0.3", "--no-save",
            capture_factory=lambda s: Endless())

        self.assertGreater(summary.frames, 3)

    def test_evaluate_refuses_a_stream(self):
        truth = self.dir / "t.csv"
        truth.write_text("type,time_seconds\nred_light,1\n")

        with contextlib.redirect_stderr(io.StringIO()) as stderr, \
                self.assertRaises(SystemExit):
            evaluate.main(["--video", "rtsp://x/y", "--truth", str(truth)])

        self.assertIn("not a live stream", stderr.getvalue())


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class PlateCommandLineTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

        for target, name, value in (
            (vl, "DB_PATH", self.dir / "t.db"),
            (run_video, "OUTPUT_DIR", self.dir / "outputs"),
        ):
            patcher = mock.patch.object(target, name, value)
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

    def test_plates_option_needs_the_reader(self):
        stderr = io.StringIO()

        with mock.patch.object(plates, "load_tools",
                               return_value=(None, None)), \
                contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit):
            run_video.main(["--input", str(self.video), "--plates",
                            "--no-display", "--no-save"])

        self.assertIn("requirements/plates.txt", stderr.getvalue())

    def test_plates_are_read_when_a_reader_is_given(self):
        with contextlib.redirect_stdout(io.StringIO()):
            summary = run_video.main(
                ["--input", str(self.video), "--output",
                 str(self.dir / "o.mp4"), "--plates", "--no-display",
                 "--no-save"],
                detector=FakeDetector(), tracker=CarMovingDown(),
                plate_reader=FakeReader([("KA01AB1234", 0.9)]))

        # The stand-in car is 40 px tall, below the default minimum size for
        # reading, so the plate stays empty rather than being guessed.
        self.assertEqual(len(summary.violations), 1)
        self.assertIsNone(summary.violations[0]["plate_text"])


if __name__ == "__main__":
    unittest.main()
