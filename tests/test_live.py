import tempfile
import threading
import time
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

from app import live, paths
from app.analysis import VideoSettings
from app.violation import violation_logger as vl
from tests.db_helpers import db_connect
from tests.test_run_video_cli import CarMovingDown, FakeDetector


def frame(value=0):
    return np.full((400, 160, 3), value, np.uint8)


class FakeCv2Capture:
    """A cv2.VideoCapture stand-in that plays a script of read results."""

    def __init__(self, script, opens=True, fps=10.0):
        self.script = list(script)
        self._opens = opens
        self.fps = fps
        self.released = False

    def isOpened(self):
        return self._opens

    def read(self):
        if self.script:
            return self.script.pop(0)

        time.sleep(0.005)

        return False, None

    def get(self, prop):
        return {cv2.CAP_PROP_FRAME_WIDTH: 160,
                cv2.CAP_PROP_FRAME_HEIGHT: 400,
                cv2.CAP_PROP_FPS: self.fps}.get(prop, 0)

    def release(self):
        self.released = True


def wait_until(condition, timeout=5.0):
    end = time.time() + timeout

    while time.time() < end:
        if condition():
            return True

        time.sleep(0.01)

    return False


class SourceTests(unittest.TestCase):

    def test_webcam_numbers_and_stream_addresses_are_accepted(self):
        self.assertEqual(live.parse_source(" 0 "), 0)
        self.assertEqual(live.parse_source("2"), 2)

        for url in ("rtsp://cam.local/stream", "http://10.0.0.5:8080/video",
                    "https://x.example/a.m3u8", "rtmp://h/app"):
            self.assertEqual(live.parse_source(url), url)

    def test_everything_else_is_refused(self):
        for bad in ("", None, "   ", "/etc/passwd", "file:///etc/passwd",
                    "C:\\video.mp4", "ftp://host/x", "rtsp://", "clip.mp4"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                live.parse_source(bad)

    def test_passwords_are_removed_for_display(self):
        shown = live.redact("rtsp://admin:secret@192.168.1.5:554/stream1")

        self.assertNotIn("secret", shown)
        self.assertNotIn("admin", shown)
        self.assertIn("192.168.1.5:554", shown)
        self.assertEqual(live.redact(0), "webcam 0")
        self.assertEqual(live.redact("rtsp://cam/x"), "rtsp://cam/x")

    def test_named_cameras_ignore_malformed_entries(self):
        value = ("Gate=rtsp://a/1; Junction = rtsp://b/2 ;bad;=rtsp://c;"
                 "NoUrl=;Evil=/etc/passwd")

        with mock.patch.dict("os.environ", {"LIVE_CAMERAS": value}):
            self.assertEqual(live.configured_cameras(), {
                "Gate": "rtsp://a/1", "Junction": "rtsp://b/2"})

        with mock.patch.dict("os.environ", {"LIVE_CAMERAS": ""}):
            self.assertEqual(live.configured_cameras(), {})

    def test_free_form_addresses_are_closed_in_production(self):
        with mock.patch.dict("os.environ", {"APP_ENV": "production"}):
            self.assertFalse(live.custom_addresses_allowed())

        with mock.patch.dict("os.environ", {"APP_ENV": "production",
                                            "LIVE_ALLOW_CUSTOM": "true"}):
            self.assertTrue(live.custom_addresses_allowed())

        with mock.patch.dict("os.environ", {"APP_ENV": ""}):
            self.assertTrue(live.custom_addresses_allowed())


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class CaptureTests(unittest.TestCase):

    def make(self, *captures, **options):
        queue = list(captures)
        options.setdefault("reconnect_delay", 0)
        options.setdefault("read_timeout", 0.5)
        capture = live.LatestFrameCapture(
            "rtsp://x/y", opener=lambda source: queue.pop(0), **options)
        self.addCleanup(capture.release)

        return capture

    def test_frames_arrive_and_properties_are_learned(self):
        capture = self.make(FakeCv2Capture([(True, frame(7))]))

        self.assertTrue(capture.wait_for_first_frame())
        ok, got = capture.read()

        self.assertTrue(ok)
        self.assertEqual(int(got[0, 0, 0]), 7)
        self.assertEqual((capture.get(cv2.CAP_PROP_FRAME_WIDTH),
                          capture.get(cv2.CAP_PROP_FRAME_HEIGHT)), (160, 400))
        self.assertEqual(capture.get(cv2.CAP_PROP_FPS), 10.0)

    def test_a_silly_frame_rate_is_replaced_by_the_default(self):
        capture = self.make(FakeCv2Capture([(True, frame())], fps=90000.0))
        capture.wait_for_first_frame()

        self.assertEqual(capture.get(cv2.CAP_PROP_FPS), live.DEFAULT_FPS)

    def test_only_the_newest_frame_is_kept_and_drops_are_counted(self):
        script = [(True, frame(i)) for i in range(1, 6)]
        capture = self.make(FakeCv2Capture(script))

        self.assertTrue(wait_until(lambda: capture._sequence >= 5))
        ok, got = capture.read()

        self.assertEqual(int(got[0, 0, 0]), 5)
        self.assertEqual(capture.dropped, 4)

    def test_the_same_frame_is_never_returned_twice(self):
        capture = self.make(FakeCv2Capture([(True, frame(1))]))
        capture.wait_for_first_frame()

        self.assertTrue(capture.read()[0])
        self.assertFalse(capture.read()[0])

    def test_it_reconnects_after_the_stream_breaks(self):
        first = FakeCv2Capture([(True, frame(1)), (False, None)])
        second = FakeCv2Capture([(True, frame(2))])
        capture = self.make(first, second)

        self.assertTrue(wait_until(lambda: capture.reconnects >= 1))
        self.assertTrue(wait_until(lambda: capture._sequence >= 2))
        self.assertTrue(first.released)

    def test_it_gives_up_after_too_many_failures(self):
        dead = [FakeCv2Capture([], opens=False) for _ in range(3)]
        capture = self.make(*dead, max_failures=3)

        self.assertTrue(wait_until(lambda: capture.finished))
        self.assertEqual(capture.status, "lost")
        self.assertIn("could not open", capture.last_error)
        self.assertFalse(capture.isOpened())
        self.assertFalse(capture.wait_for_first_frame(timeout=0.1))

    def test_any_error_from_the_camera_library_means_retry(self):
        calls = []

        def opener(source):
            calls.append(source)

            if len(calls) == 1:
                raise OSError("driver said no for rtsp://u:pw@h/x")

            return FakeCv2Capture([(True, frame(3))])

        capture = live.LatestFrameCapture(
            "rtsp://u:pw@h/x", opener=opener, reconnect_delay=0)
        self.addCleanup(capture.release)

        self.assertTrue(capture.wait_for_first_frame())
        self.assertEqual(len(calls), 2)
        self.assertEqual(capture.reconnects, 1)
        self.assertNotIn("pw", capture.last_error)

    def test_release_stops_the_reader_and_closes_the_camera(self):
        camera = FakeCv2Capture([(True, frame())])
        capture = self.make(camera)
        capture.wait_for_first_frame()
        capture.release()

        self.assertTrue(wait_until(lambda: capture.finished))
        self.assertTrue(camera.released)
        self.assertEqual(capture.status, "stopped")

    def test_a_retry_pause_ends_as_soon_as_we_stop(self):
        capture = self.make(
            FakeCv2Capture([], opens=False), reconnect_delay=60)
        wait_until(lambda: capture.status == "reconnecting")
        started = time.time()
        capture.release()

        self.assertLess(time.time() - started, 3)


class ListCapture:
    """A finite, instantly-served source for driving the monitor."""

    def __init__(self, frames=9):
        self.frames = [frame() for _ in range(frames)]
        self.status = "running"
        self.reconnects = 0
        self.dropped = 0
        self.last_error = ""
        self.finished = False
        self.released = False

    def wait_for_first_frame(self, timeout=15.0):
        return True

    def isOpened(self):
        return not self.finished

    def read(self):
        if self.frames:
            return True, self.frames.pop(0)

        self.finished = True

        return False, None

    def get(self, prop):
        return {cv2.CAP_PROP_FRAME_WIDTH: 160,
                cv2.CAP_PROP_FRAME_HEIGHT: 400,
                cv2.CAP_PROP_FPS: 10.0}.get(prop, 0)

    def release(self):
        self.released = True


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class MonitorTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        for target, name, value in (
            (vl, "DB_PATH", self.db),
            (paths, "OUTPUT_DIR", self.dir / "outputs"),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def monitor(self, capture, settings=None, **options):
        monitor = live.LiveMonitor(
            settings or VideoSettings(camera_id="GATE-1"),
            "Gate", "rtsp://x/y", FakeDetector(), CarMovingDown(),
            capture_factory=lambda source: capture, **options)
        monitor.start()
        self.addCleanup(monitor.stop)

        return monitor

    def test_it_runs_the_pipeline_and_records_the_violation(self):
        capture = ListCapture()
        monitor = self.monitor(capture)

        self.assertTrue(wait_until(lambda: not monitor.active))
        self.assertEqual(monitor.state, "stopped")
        self.assertEqual(monitor.violations, 1)
        self.assertIn("red_light, track 5", monitor.recent[0])
        self.assertTrue(capture.released)

        with db_connect(self.db) as conn:
            rows = conn.execute(
                "SELECT source, camera_id, evidence_path "
                "FROM violation_records").fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:2], ("live:Gate", "GATE-1"))
        self.assertIn(str(self.dir / "outputs" / "live"), rows[0][2])
        self.assertTrue(Path(rows[0][2]).is_file())

    def test_the_snapshot_describes_the_run(self):
        monitor = self.monitor(ListCapture())
        wait_until(lambda: not monitor.active)
        snap = monitor.snapshot()

        self.assertEqual(snap["camera"], "Gate")
        self.assertEqual(snap["state"], "stopped")
        self.assertEqual(snap["frames_analyzed"], 9)
        self.assertEqual(snap["violations"], 1)
        self.assertNotIn("rtsp", str(snap))

    def test_a_preview_image_is_made(self):
        monitor = self.monitor(ListCapture())
        wait_until(lambda: not monitor.active)

        self.assertTrue(monitor.latest_jpeg().startswith(b"\xff\xd8"))

    def test_not_saving_leaves_the_database_alone(self):
        monitor = self.monitor(
            ListCapture(), VideoSettings(save_to_db=False))
        wait_until(lambda: not monitor.active)

        self.assertEqual(monitor.violations, 1)
        self.assertFalse(self.db.exists())

    def test_stop_ends_an_endless_stream(self):
        class Endless(ListCapture):
            def read(self):
                time.sleep(0.005)

                return True, frame()

        capture = Endless()
        monitor = self.monitor(capture)
        self.assertTrue(wait_until(lambda: monitor.state == "running"))
        monitor.stop()

        self.assertFalse(monitor.active)
        self.assertEqual(monitor.state, "stopped")
        self.assertTrue(capture.released)

    def test_max_seconds_ends_the_run(self):
        class Endless(ListCapture):
            def read(self):
                time.sleep(0.005)

                return True, frame()

        monitor = self.monitor(Endless(), max_seconds=0.3)

        self.assertTrue(wait_until(lambda: not monitor.active, timeout=5))
        self.assertEqual(monitor.state, "stopped")

    def test_a_camera_that_never_answers_is_a_clear_failure(self):
        class Silent(ListCapture):
            def __init__(self):
                super().__init__()
                self.last_error = "could not open the camera"

            def wait_for_first_frame(self, timeout=15.0):
                return False

        monitor = self.monitor(Silent())
        wait_until(lambda: not monitor.active)

        self.assertEqual(monitor.state, "failed")
        self.assertIn("no picture arrived", monitor.error)
        self.assertIn("could not open", monitor.error)

    def test_losing_the_camera_marks_the_run_failed(self):
        class Lost(ListCapture):
            def read(self):
                ok, got = super().read()

                if not ok:
                    self.status = "lost"
                    self.last_error = "the stream stopped sending frames"

                return ok, got

        monitor = self.monitor(Lost())
        wait_until(lambda: not monitor.active)

        self.assertEqual(monitor.state, "failed")
        self.assertIn("lost the camera", monitor.error)

    def test_a_crash_inside_the_worker_is_reported_not_swallowed(self):
        def broken(source):
            raise RuntimeError("driver exploded")

        monitor = live.LiveMonitor(
            VideoSettings(), "Gate", "rtsp://x/y", FakeDetector(),
            CarMovingDown(), capture_factory=broken)
        monitor.start()
        wait_until(lambda: not monitor.active)

        self.assertEqual(monitor.state, "failed")
        self.assertIn("driver exploded", monitor.error)

    def test_recent_events_are_capped(self):
        monitor = live.LiveMonitor(
            VideoSettings(), "G", "0", FakeDetector(), CarMovingDown())

        for number in range(30):
            monitor._on_event("violation", {"type": "red_light",
                                            "track_id": number})

        self.assertEqual(len(monitor.recent), 20)
        self.assertIn("track 29", monitor.recent[0])
        self.assertEqual(monitor.violations, 30)

    def test_plates_appear_in_the_event_text(self):
        monitor = live.LiveMonitor(
            VideoSettings(), "G", "0", FakeDetector(), CarMovingDown())
        monitor._on_event("violation", {
            "type": "red_light", "track_id": 3, "plate_text": "KA01AB1234"})

        self.assertIn("plate KA01AB1234", monitor.recent[0])


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class LiveClockTests(unittest.TestCase):
    """The processor's live mode uses the wall clock for time."""

    def test_dropped_frames_do_not_stretch_time(self):
        from app.video_processor import TrafficVideoProcessor

        class SlowDetector:
            def detect(self, image):
                time.sleep(0.05)

                return []

        class Capture(ListCapture):
            pass

        processor = TrafficVideoProcessor(
            detector=SlowDetector(), tracker=CarMovingDown(),
            stop_line_y=240, signal_state="GREEN",
            evidence_dir=tempfile.mkdtemp())
        summary = processor.process(
            None, None, capture=Capture(frames=6), live=True,
            show=False, save_to_db=False)

        # 6 frames at ~0.05 s each is ~0.3 s of real time; at 10 FPS that is
        # at least ~3 ticks, so the last timestamp must reflect real time.
        self.assertEqual(summary.frames, 6)
        self.assertGreaterEqual(summary.duration_seconds, 0.6 * 0.5)
        self.assertIsNone(summary.output_path)


if __name__ == "__main__":
    unittest.main()
