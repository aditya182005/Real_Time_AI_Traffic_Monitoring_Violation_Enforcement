"""End-to-end runs of TrafficVideoProcessor with scripted vehicles.

A scripted tracker stands in for YOLO + ByteTrack, so these tests exercise
the real processor, detectors, evidence saving and database logging on a
real (synthetic) video file without needing any model.
"""

import sqlite3

from tests.db_helpers import db_connect
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

from app.video_processor import (
    SpeedConfig,
    TrafficVideoProcessor,
    WrongWayConfig,
)
from app.violation import violation_logger as vl
from app.violation.signal import SignalSimulator

W, H, FPS = 320, 400, 10


class NoDetector:
    def detect(self, frame, conf=None):
        return []


class ScriptedTracker:
    """frames: list (one per frame) of [(track_id, x1, y1, x2, y2), ...]."""

    def __init__(self, frames):
        self.frames = frames
        self.index = 0

    def update(self, detections):
        rows = self.frames[self.index]
        self.index += 1

        return SimpleNamespace(
            xyxy=np.array([r[1:] for r in rows], dtype=float).reshape(-1, 4),
            tracker_id=np.array([r[0] for r in rows], dtype=int),
            class_id=np.full(len(rows), 2, dtype=int),
        )


class FakeEmergency:
    def __init__(self, active_frames):
        self.active = set(active_frames)
        self.frame = 0

    def detect(self, frame, conf=None):
        self.frame += 1

        if self.frame in self.active:
            return [{"class_id": 0, "class_name": "ambulance",
                     "confidence": 0.9, "bbox": (10, 10, 60, 60)}]

        return []


def car(track_id, bottom, cx=100, w=40, h=40):
    return (track_id, cx - w // 2, bottom - h, cx + w // 2, bottom)


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class PipelineTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_video(self, frames):
        path = self.dir / "in.mp4"
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H)
        )

        if not writer.isOpened():
            self.skipTest("this OpenCV build cannot write mp4v video")

        for _ in range(frames):
            writer.write(np.zeros((H, W, 3), dtype=np.uint8))

        writer.release()

        return path

    def run_pipeline(self, script, **kwargs):
        kwargs.setdefault("stop_line_y", 395)        # out of the way
        kwargs.setdefault("signal_state", "GREEN")

        processor = TrafficVideoProcessor(
            detector=NoDetector(),
            tracker=ScriptedTracker(script),
            evidence_dir=self.dir / "evidence",
            **kwargs,
        )

        return processor.process(
            self.make_video(len(script)), self.dir / "out.mp4",
            show=False, source="clip.mp4", run_id="r1",
        )

    def rows(self, sql):
        if not self.db.exists():
            return []

        with db_connect(self.db) as conn:
            return conn.execute(sql).fetchall()

    # -- speeding ---------------------------------------------------------

    def test_speeding_is_measured_and_only_the_fast_car_is_fined(self):
        # Car 1: 10 px/frame -> 100 px in 1 s = 10 m/s = 36 km/h (limit 30).
        # Car 2: 4 px/frame  -> 14.4 km/h, under the limit.
        script = [
            [car(1, 100 + 10 * f), car(2, 100 + 4 * f, cx=250)]
            for f in range(40)
        ]
        summary = self.run_pipeline(
            script, speed=SpeedConfig(150, 250, 10.0, 30.0),
            camera_id="CAM-9",
        )

        speeding = summary.violations_of("speeding")
        self.assertEqual([v["track_id"] for v in speeding], [1])
        self.assertAlmostEqual(speeding[0]["speed_kmh"], 36.0)

        rows = self.rows(
            "SELECT violation_type, measured_speed, speed_limit, fine_amount,"
            " camera_id, source FROM violation_records")
        self.assertEqual(rows, [("speeding", 36.0, 30.0, 600, "CAM-9",
                                 "clip.mp4")])

    def test_speed_checks_are_off_unless_configured(self):
        script = [[car(1, 100 + 10 * f)] for f in range(40)]

        self.assertEqual(self.run_pipeline(script).violations, [])

    # -- wrong way --------------------------------------------------------

    def test_wrong_way_vehicle_is_flagged_and_logged(self):
        script = [[car(3, 350 - 8 * f)] for f in range(30)]
        summary = self.run_pipeline(
            script, wrong_way=WrongWayConfig(expected="down")
        )

        self.assertEqual(
            [v["track_id"] for v in summary.violations_of("wrong_way")], [3]
        )
        self.assertEqual(
            self.rows("SELECT violation_type, fine_amount "
                      "FROM violation_records"),
            [("wrong_way", vl.WRONG_WAY_FINE)],
        )
        crop = Path(summary.violations[0]["crop_path"])
        self.assertTrue(crop.is_file())

    # -- collisions -------------------------------------------------------

    def collision_script(self):
        approach = [(20 + 10 * f, 220 - 10 * f) for f in range(10)]
        positions = approach + [approach[-1]] * 8

        return [
            [(1, a - 20, 80, a + 20, 120), (2, b - 20, 80, b + 20, 120)]
            for a, b in positions
        ]

    def test_collision_is_logged_once_with_alerts_off_by_default(self):
        summary = self.run_pipeline(
            self.collision_script(), detect_collisions=True
        )

        self.assertEqual(len(summary.collisions), 1)
        self.assertIn("alerts off", summary.collisions[0]["alert_status"])

        rows = self.rows("SELECT track_id_1, track_id_2, alert_status "
                         "FROM collision_events")
        self.assertEqual(len(rows), 1)
        self.assertIn("alerts off", rows[0][2])
        self.assertTrue(Path(summary.collisions[0]["evidence_path"]).is_file())

    def test_collision_alert_outcome_reaches_summary_and_database(self):
        sent = []

        def sender(message):
            sent.append(message)
            return "sent"

        summary = self.run_pipeline(
            self.collision_script(), detect_collisions=True,
            send_collision_alerts=True, alert_sender=sender,
            camera_id="CAM-3",
        )

        self.assertEqual(summary.collisions[0]["alert_status"], "sent")
        self.assertEqual(
            self.rows("SELECT alert_status FROM collision_events"),
            [("sent",)],
        )
        # The alert names the camera and asks for verification.
        self.assertIn("CAM-3", sent[0])
        # The plan asks for the camera ID *and a timestamp* in every alert.
        self.assertRegex(
            sent[0], r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC")
        self.assertIn("verify", sent[0].lower())

    def test_no_collision_check_unless_enabled(self):
        summary = self.run_pipeline(self.collision_script())

        self.assertEqual(summary.collisions, [])

    # -- emergency override ----------------------------------------------

    def crossing_script(self):
        # One car crosses a stop line at y=250 while the signal is red.
        return [[car(5, 100 + 10 * f)] for f in range(30)]

    def test_red_light_is_flagged_without_an_emergency(self):
        summary = self.run_pipeline(
            self.crossing_script(), stop_line_y=250, signal_state="RED"
        )

        self.assertEqual(len(summary.violations_of("red_light")), 1)

    def test_emergency_vehicle_overrides_the_signal_to_green(self):
        summary = self.run_pipeline(
            self.crossing_script(), stop_line_y=250, signal_state="RED",
            emergency_detector=FakeEmergency(range(1, 6)),
            priority_hold_seconds=3.0, camera_id="CAM-2",
        )

        # Priority confirmed after 3 frames; hold covers the crossing.
        self.assertEqual(summary.violations_of("red_light"), [])
        self.assertEqual(len(summary.emergency_events), 1)
        self.assertTrue(summary.emergency_events[0]["signal_override"])

        self.assertEqual(
            self.rows("SELECT vehicle_class, signal_override, camera_id "
                      "FROM priority_events"),
            [("ambulance", 1, "CAM-2")],
        )

    def test_override_ends_after_the_hold_time(self):
        # Hold of 0.5 s = 5 frames; the crossing is at frame ~16, after it.
        summary = self.run_pipeline(
            self.crossing_script(), stop_line_y=250, signal_state="RED",
            emergency_detector=FakeEmergency(range(1, 4)),
            priority_hold_seconds=0.5,
        )

        self.assertEqual(len(summary.violations_of("red_light")), 1)

    def test_a_single_noisy_emergency_detection_does_nothing(self):
        summary = self.run_pipeline(
            self.crossing_script(), stop_line_y=250, signal_state="RED",
            emergency_detector=FakeEmergency([1]),   # one frame only
        )

        self.assertEqual(summary.emergency_events, [])
        self.assertEqual(len(summary.violations_of("red_light")), 1)

    # -- cycling signal, preview, bookkeeping -----------------------------

    def test_crossing_on_green_phase_of_a_cycle_is_not_a_violation(self):
        # 1 s red then 9 s green; the car crosses around t=1.6 s (green).
        summary = self.run_pipeline(
            self.crossing_script(), stop_line_y=250,
            signal=SignalSimulator.cycle(1, 9),
        )

        self.assertEqual(summary.violations, [])

    def test_live_preview_and_progress_callbacks(self):
        previews, progress = [], []
        script = [[car(1, 100 + 4 * f)] for f in range(12)]

        processor = TrafficVideoProcessor(
            detector=NoDetector(), tracker=ScriptedTracker(script),
            evidence_dir=self.dir / "ev", stop_line_y=395,
            signal_state="GREEN",
        )
        summary = processor.process(
            self.make_video(12), self.dir / "o.mp4", show=False,
            frame_callback=lambda f, n: previews.append((f.shape, n)),
            preview_every=4, progress=lambda d, t: progress.append(d),
        )

        self.assertEqual([n for _, n in previews], [4, 8, 12])
        self.assertEqual(previews[0][0], (H, W, 3))
        self.assertEqual(progress[-1], 12)
        self.assertEqual(summary.frames, 12)
        self.assertGreater(summary.processing_fps, 0)

    def test_density_is_saved_per_second(self):
        script = [[car(1, 100 + 4 * f), car(2, 80, cx=250)]
                  for f in range(25)]
        self.run_pipeline(script)

        rows = self.rows(
            "SELECT video_second, vehicle_count, camera_id "
            "FROM traffic_density ORDER BY video_second")

        self.assertEqual([r[0] for r in rows], [0, 1, 2])
        self.assertEqual({r[1] for r in rows}, {2.0})
        self.assertEqual({r[2] for r in rows}, {"CAM-01"})

    def test_nothing_is_written_when_saving_is_off(self):
        script = [[car(5, 100 + 10 * f)] for f in range(30)]
        processor = TrafficVideoProcessor(
            detector=NoDetector(), tracker=ScriptedTracker(script),
            evidence_dir=self.dir / "ev", stop_line_y=250,
            signal_state="RED",
        )
        summary = processor.process(
            self.make_video(30), self.dir / "o.mp4", show=False,
            save_to_db=False,
        )

        self.assertEqual(len(summary.violations_of("red_light")), 1)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
