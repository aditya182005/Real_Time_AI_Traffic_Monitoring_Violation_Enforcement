"""Zones, calibration, benchmark, traffic stats, digest, adaptive loop."""

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark  # noqa: E402
import train_helmet  # noqa: E402

from app import calibration, digest, traffic_stats  # noqa: E402
from app.annotate import explain  # noqa: E402
from app.signals.loop import AdaptiveSignal  # noqa: E402
from app.violation import violation_logger as vl  # noqa: E402
from app.violation import zones  # noqa: E402
from tests.db_helpers import db_connect  # noqa: E402

SQUARE = [(100, 100), (300, 100), (300, 300), (100, 300)]


class ZoneRuleTests(unittest.TestCase):

    def test_point_in_polygon(self):
        self.assertTrue(zones.point_in_polygon(200, 200, SQUARE))
        self.assertFalse(zones.point_in_polygon(50, 200, SQUARE))
        self.assertFalse(zones.point_in_polygon(200, 350, SQUARE))

    def test_parking_needs_time_and_stillness(self):
        monitor = zones.ParkingMonitor(SQUARE, seconds=10)
        box = (150, 150, 250, 250)

        self.assertFalse(monitor.update(1, box, 0))
        self.assertFalse(monitor.update(1, box, 9))
        self.assertTrue(monitor.update(1, box, 10))
        self.assertFalse(monitor.update(1, box, 20))     # only once

    def test_a_moving_vehicle_is_not_parked(self):
        monitor = zones.ParkingMonitor(SQUARE, seconds=10)

        for second in range(0, 30, 2):
            x = 120 + second * 5
            self.assertFalse(monitor.update(1, (x, 150, x + 60, 250), second))

    def test_leaving_the_zone_resets_the_timer(self):
        monitor = zones.ParkingMonitor(SQUARE, seconds=10)
        inside, outside = (150, 150, 250, 250), (500, 150, 600, 250)
        monitor.update(1, inside, 0)
        monitor.update(1, outside, 8)

        self.assertFalse(monitor.update(1, inside, 12))
        self.assertTrue(monitor.update(1, inside, 22))

    def test_crossing_only_when_red_and_standing(self):
        monitor = zones.CrossingMonitor(380, 440, hold=2)
        box = (100, 300, 200, 410)

        self.assertFalse(monitor.update(1, box, "GREEN", 0))
        self.assertFalse(monitor.update(1, box, "GREEN", 5))
        self.assertFalse(monitor.update(1, box, "RED", 6))
        self.assertTrue(monitor.update(1, box, "RED", 8.5))

    def test_a_vehicle_rolling_across_on_red_is_not_standing(self):
        monitor = zones.CrossingMonitor(380, 440, hold=2)

        for i in range(10):
            y = 370 + i * 12
            self.assertFalse(monitor.update(1, (100, y - 100, 200, y), "RED", i))

    def test_restricted_lane_flags_the_wrong_class_only(self):
        rule = zones.RestrictedLane(SQUARE, {"motorcycle"}, persist=3)
        box = (150, 150, 250, 250)
        results = [rule.update(1, box, "car") for _ in range(4)]

        self.assertEqual(results, [False, False, True, False])
        self.assertFalse(any(rule.update(2, box, "motorcycle")
                             for _ in range(5)))

    def test_triple_riding_counts_heads_on_the_bike(self):
        bike = (100, 200, 160, 300)

        def heads(n):
            return [{"bbox": (100 + 12 * i, 150, 125 + 12 * i, 185),
                     "confidence": 0.9, "class_name": "helmet"}
                    for i in range(n)]

        rule = zones.TripleRiding(confirm=2)
        self.assertFalse(any(rule.update(1, bike, heads(2)) for _ in range(5)))
        self.assertFalse(rule.update(2, bike, heads(3)))
        self.assertTrue(rule.update(2, bike, heads(3)))

    def test_config_parsing_and_errors(self):
        config = zones.ZoneConfig.parse({
            "no_parking": {"polygon": SQUARE, "seconds": 20},
            "crossing": {"y_top": 380, "y_bottom": 440},
            "restricted_lane": {"polygon": SQUARE, "allowed": ["bus"]},
            "triple_riding": True})
        self.assertTrue(config.active)
        self.assertEqual(config.no_parking["seconds"], 20.0)

        for bad in ([], {"nothing": 1},
                    {"no_parking": {"polygon": [[1, 1], [2, 2]]}},
                    {"crossing": {"y_top": 5, "y_bottom": 1}},
                    {"restricted_lane": {"polygon": SQUARE, "allowed": []}},
                    {"no_parking": {"polygon": SQUARE, "seconds": 0}}):
            with self.assertRaises(zones.ZoneConfigError, msg=bad):
                zones.ZoneConfig.parse(bad)

    def test_empty_config_is_inactive(self):
        self.assertFalse(zones.ZoneConfig.parse({}).active)

    def test_bad_file_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "z.json"
            path.write_text("{oops")

            with self.assertRaises(zones.ZoneConfigError):
                zones.ZoneConfig.load(path)

            with self.assertRaises(zones.ZoneConfigError):
                zones.ZoneConfig.load(Path(tmp) / "missing.json")


class FineTests(unittest.TestCase):

    def test_new_types_have_fines_and_can_be_overridden(self):
        for kind, amount in (("illegal_parking", 500),
                             ("crossing_encroachment", 500),
                             ("wrong_lane", 1000), ("triple_riding", 1000)):
            self.assertEqual(vl.calculate_fine(kind), amount)

        from app import fines

        self.assertEqual(fines.parse({"wrong_lane": 250})["wrong_lane"], 250)

    def test_explanations(self):
        self.assertIn("RED", explain("red_light", "RED"))
        self.assertIn("72", explain("speeding", speed_kmh=72))

        for kind in zones.KINDS:
            self.assertNotEqual(explain(kind), kind)


class CalibrationTests(unittest.TestCase):

    def test_straight_on_view_gives_the_real_length(self):
        # 100 px wide = 3 m, 400 px long = 12 m  -> 0.03 m per pixel
        c = calibration.Calibration(
            [(0, 400), (100, 400), (100, 0), (0, 0)], 3, 12)

        self.assertAlmostEqual(c.distance_between_rows(400, 0), 12, places=6)
        self.assertAlmostEqual(c.distance_between_rows(300, 100), 6, places=6)

    def test_perspective_makes_far_pixels_longer(self):
        # A trapezoid: the far edge is narrower, so far pixels cover more road.
        c = calibration.Calibration(
            [(0, 400), (200, 400), (150, 0), (50, 0)], 4, 20)

        near = c.distance_between_rows(400, 300)
        far = c.distance_between_rows(100, 0)

        self.assertGreater(far, near)
        self.assertAlmostEqual(c.distance_between_rows(400, 0), 20, places=5)

    def test_bad_points_are_rejected(self):
        with self.assertRaises(calibration.CalibrationError):
            calibration.Calibration([(0, 0), (1, 1), (2, 2), (3, 3)], 3, 10)

        with self.assertRaises(calibration.CalibrationError):
            calibration.Calibration([(0, 0)] * 3, 3, 10)

        with self.assertRaises(calibration.CalibrationError):
            calibration.Calibration([(0, 1), (1, 1), (1, 0), (0, 0)], 0, 10)

    def test_save_and_load_round_trip(self):
        c = calibration.Calibration([(0, 400), (100, 400), (100, 0), (0, 0)],
                                    3, 12)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            c.save(path)
            again = calibration.Calibration.load(path)

        self.assertAlmostEqual(again.distance_between_rows(400, 0), 12)

        with self.assertRaises(calibration.CalibrationError):
            calibration.Calibration.from_dict({"image_points": []})

    def test_script_points_parser(self):
        import calibrate_speed

        self.assertEqual(len(calibrate_speed.parse_points("0,0;1,0;1,1;0,1")), 4)

        with self.assertRaises(calibration.CalibrationError):
            calibrate_speed.parse_points("0,0;1,0")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "c.json"
            calibrate_speed.main(["--points", "0,400;100,400;100,0;0,0",
                                  "--width-m", "3", "--length-m", "12",
                                  "--output", str(out), "--rows", "400,0"])
            self.assertTrue(out.exists())


class BenchmarkTests(unittest.TestCase):

    def test_matching_counts_tp_fp_fn(self):
        truth = [("a.mp4", "red_light", 10), ("a.mp4", "red_light", 40),
                 ("b.mp4", "speeding", 5)]
        found = [("a.mp4", "red_light", 11.5),     # TP
                 ("a.mp4", "red_light", 80),       # FP, nothing near
                 ("b.mp4", "speeding", 5.5),       # TP
                 ("b.mp4", "wrong_way", 3)]        # FP, never in truth
        counts = benchmark.match(truth, found, tolerance=3)

        self.assertEqual(counts["red_light"], {"tp": 1, "fp": 1, "fn": 1})
        self.assertEqual(counts["speeding"], {"tp": 1, "fp": 0, "fn": 0})
        self.assertEqual(counts["wrong_way"], {"tp": 0, "fp": 1, "fn": 0})

    def test_a_truth_row_is_used_once(self):
        counts = benchmark.match([("a.mp4", "red_light", 10)],
                                 [("a.mp4", "red_light", 10),
                                  ("a.mp4", "red_light", 11)])

        self.assertEqual(counts["red_light"], {"tp": 1, "fp": 1, "fn": 0})

    def test_other_clip_or_type_never_matches(self):
        counts = benchmark.match([("a.mp4", "red_light", 10)],
                                 [("b.mp4", "red_light", 10),
                                  ("a.mp4", "speeding", 10)])

        self.assertEqual(counts["red_light"]["fn"], 1)

    def test_scores_and_wilson_interval(self):
        result = benchmark.scores({"x": {"tp": 8, "fp": 2, "fn": 0}})["x"]

        self.assertAlmostEqual(result["precision"], 0.8)
        self.assertEqual(result["recall"], 1.0)
        self.assertAlmostEqual(result["recall_low"], 0.676, places=2)
        self.assertEqual(result["recall_high"], 1.0)
        self.assertEqual(benchmark.wilson(0, 0), (None, None))

    def test_no_data_is_not_reported_as_zero(self):
        result = benchmark.scores({"x": {"tp": 0, "fp": 0, "fn": 0}})["x"]

        self.assertIsNone(result["precision"])
        self.assertIsNone(result["recall"])

    def test_truth_file_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "t.csv"
            good.write_text("clip,type,time_seconds\na.mp4,red_light,12.5\n")
            self.assertEqual(benchmark.read_truth(good),
                             [("a.mp4", "red_light", 12.5)])

            bad = Path(tmp) / "b.csv"
            bad.write_text("clip,type,time_seconds\na.mp4,red_light,soon\n")

            with self.assertRaises(benchmark.TruthError):
                benchmark.read_truth(bad)

            wrong = Path(tmp) / "w.csv"
            wrong.write_text("name,kind\na,b\n")

            with self.assertRaises(benchmark.TruthError):
                benchmark.read_truth(wrong)

            with self.assertRaises(benchmark.TruthError):
                benchmark.read_truth(Path(tmp) / "none.csv")

    def test_end_to_end_with_a_fake_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            clips = tmp / "clips"
            clips.mkdir()
            (clips / "a.mp4").write_bytes(b"x")
            truth = clips / "truth.csv"
            truth.write_text("clip,type,time_seconds\na.mp4,red_light,5\n")

            def runner(argv):
                return SimpleNamespace(
                    frames=300, video_fps=30.0,
                    violations=[{"type": "red_light", "time_seconds": 5.4}],
                    collisions=[])

            result = benchmark.main(
                ["--clips", str(clips), "--truth", str(truth),
                 "--report", str(tmp / "r"), "--", "--speed"], runner=runner)

            self.assertEqual(result["red_light"]["tp"], 1)
            self.assertIn("red_light", (tmp / "r.md").read_text())
            self.assertEqual(
                json.loads((tmp / "r.json").read_text())["clips"], 1)

            truth.write_text("clip,type,time_seconds\nghost.mp4,red_light,5\n")

            with self.assertRaises(SystemExit):
                benchmark.main(["--clips", str(clips), "--truth", str(truth),
                                "--report", str(tmp / "r2")], runner=runner)


class TrafficStatsTests(unittest.TestCase):

    def test_levels(self):
        self.assertEqual(traffic_stats.congestion_level(2, 6, 14), "Free")
        self.assertEqual(traffic_stats.congestion_level(6, 6, 14), "Moderate")
        self.assertEqual(traffic_stats.congestion_level(20, 6, 14), "Heavy")
        self.assertIsNone(traffic_stats.congestion_level(None, 6, 14))

    def test_thresholds_from_environment(self):
        with mock.patch.dict(os.environ, {"CONGESTION_MODERATE": "3",
                                          "CONGESTION_HEAVY": "8"}):
            self.assertEqual(traffic_stats.thresholds(), (3.0, 8.0))
            self.assertEqual(traffic_stats.congestion_level(9), "Heavy")

        with mock.patch.dict(os.environ, {"CONGESTION_MODERATE": "x"}):
            self.assertEqual(traffic_stats.thresholds()[0], 6.0)

    def test_hours_without_data_are_not_called_free(self):
        hourly = pd.DataFrame({"Hour (UTC)": [8, 9, 10],
                               "Avg vehicles in view": [3.0, 20.0, float("nan")]})
        table = traffic_stats.congestion_by_hour(hourly)

        self.assertEqual(list(table["Level"][:2]), ["Free", "Heavy"])
        self.assertTrue(pd.isna(table["Level"][2]))
        top, low = traffic_stats.busiest_and_quietest(hourly)
        self.assertEqual((top[0], low[0]), (9, 8))

    def test_class_totals(self):
        frame = pd.DataFrame({"vehicle_class": ["car", "car", "bus"],
                              "vehicle_count": [5, 3, 1]})
        table = traffic_stats.class_totals(frame)

        self.assertEqual(table.iloc[0]["Vehicle class"], "car")
        self.assertEqual(table.iloc[0]["Vehicles"], 8)
        self.assertTrue(traffic_stats.class_totals(None).empty)

    def test_heatmap_grid(self):
        frame = pd.DataFrame({"pos_x": [0.1, 0.1, 0.95, None],
                              "pos_y": [0.1, 0.12, 0.9, 0.5]})
        grid = traffic_stats.heatmap_grid(frame, bins=4)

        self.assertEqual(int(grid.at[0, 0]), 2)
        self.assertEqual(int(grid.at[3, 3]), 1)
        self.assertEqual(int(grid.values.sum()), 3)
        self.assertIsNone(traffic_stats.heatmap_grid(
            pd.DataFrame({"pos_x": [None], "pos_y": [None]})))
        self.assertIsNone(traffic_stats.heatmap_grid(pd.DataFrame()))


class AdaptiveSignalTests(unittest.TestCase):

    def greens(self, queue, seconds=300):
        signal = AdaptiveSignal()
        signal.observe_queue(queue)

        for frame in range(1, seconds * 10 + 1):
            signal.state_at(frame, 10)

        return signal.greens

    def test_green_length_follows_the_queue(self):
        long = self.greens(30)
        short = self.greens(2)

        self.assertTrue(long and short)
        self.assertGreater(long[0][1], short[0][1])
        self.assertEqual(short[0][1], 10)          # the minimum
        self.assertEqual(long[0][1], 60)           # capped at the maximum

    def test_it_cycles_red_and_green(self):
        signal = AdaptiveSignal()
        seen = {signal.state_at(f, 10) for f in range(1, 3000)}

        self.assertEqual(seen, {"RED", "GREEN"})

    def test_rates_must_match_the_other_approaches(self):
        with self.assertRaises(ValueError):
            AdaptiveSignal(other_rates=(0.1, 0.1))

    def test_a_processor_run_feeds_the_queue(self):
        signal = AdaptiveSignal()
        signal.observe_queue(7)
        self.assertEqual(signal.queue, 7)
        signal.observe_queue(-3)
        self.assertEqual(signal.queue, 0)


class TrainHelmetTests(unittest.TestCase):

    def yaml(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "data.yaml"
        path.write_text(text)

        return path

    def test_class_names_in_each_yaml_style(self):
        self.assertEqual(train_helmet.class_names(
            self.yaml("names: ['helmet', 'no_helmet']\n")),
            ["helmet", "no_helmet"])
        self.assertEqual(train_helmet.class_names(
            self.yaml("names:\n  0: helmet\n  1: head\nnc: 2\n")),
            ["helmet", "head"])
        self.assertEqual(train_helmet.class_names(
            self.yaml("names:\n- helmet\n- no helmet\n")),
            ["helmet", "no helmet"])

    def test_both_kinds_are_required(self):
        train_helmet.check_classes(self.yaml("names: [helmet, head]\n"))

        with self.assertRaises(ValueError):
            train_helmet.check_classes(self.yaml("names: [helmet]\n"))

        with self.assertRaises(ValueError):
            train_helmet.check_classes(self.yaml("names: [car, bus]\n"))

    def test_main_stops_before_training_on_bad_classes(self):
        calls = []
        code = train_helmet.main(
            ["--data", str(self.yaml("names: [helmet]\n"))],
            trainer=lambda *a, **k: calls.append(1))

        self.assertEqual(code, 1)
        self.assertEqual(calls, [])


class DigestTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "t.db"
        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_counts_pending_and_head_hash(self):
        evidence = Path(self.tmp.name) / "e.jpg"
        evidence.write_bytes(b"x")
        vl.log_violation("a", 1, "red_light", evidence)
        vl.log_violation("b", 2, "no_helmet", evidence)
        text = digest.build(db_path=self.db)

        self.assertIn("violations: 2", text)
        self.assertIn("red_light 1", text)
        self.assertIn("waiting for review: 2", text)
        self.assertIn("Head hash: ", text)
        self.assertNotIn("Head hash: -", text)
        self.assertIn("OK", text)

    def test_no_database_is_not_a_crash(self):
        self.assertIn("no database", digest.build(
            db_path=Path(self.tmp.name) / "nodir" / "x.db"))

    def test_send_uses_the_sender_and_respects_the_off_switch(self):
        sent = []
        status = digest.send("hello", sender=lambda m: sent.append(m) or "sent")

        self.assertEqual((status, sent), ("sent", ["hello"]))

        with mock.patch.dict(os.environ, {"DIGEST": "off"}):
            self.assertIn("off", digest.send("hello",
                                             sender=lambda m: 1 / 0))

    def test_a_failing_sender_never_raises(self):
        self.assertTrue(digest.send("x", sender=lambda m: 1 / 0)
                        .startswith("failed"))

    def test_unconfigured_telegram_is_skipped(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "",
                                          "TELEGRAM_CHAT_ID": ""}):
            self.assertIn("not configured", digest.send("x"))


class FakeTracker:
    """One vehicle that never moves, then a second that is a bus."""

    def __init__(self, boxes, classes):
        self.boxes, self.classes = boxes, classes

    def update(self, detections):
        return SimpleNamespace(
            xyxy=np.array(self.boxes, float),
            tracker_id=np.arange(1, len(self.boxes) + 1),
            class_id=np.array(self.classes))


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class PipelineTests(unittest.TestCase):

    def run_pipeline(self, zone_data, boxes, classes, signal=None, frames=40,
                     fps=10):
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
                                 fps, (640, 480))

        if not writer.isOpened():
            self.skipTest("cannot write mp4v")

        for _ in range(frames):
            writer.write(np.zeros((480, 640, 3), np.uint8))

        writer.release()
        processor = TrafficVideoProcessor(
            detector=mock.Mock(detect=lambda f: []),
            tracker=FakeTracker(boxes, classes),
            signal=signal, signal_state="GREEN", evidence_dir=d / "ev",
            zones=zones.ZoneConfig.parse(zone_data))
        summary = processor.process(video, d / "out.mp4", show=False)

        with db_connect(db) as conn:
            rows = conn.execute(
                "SELECT violation_type, fine_amount, pos_x, pos_y "
                "FROM violation_records").fetchall()
            counts = conn.execute(
                "SELECT vehicle_class, vehicle_count FROM vehicle_counts"
            ).fetchall()

        return summary, rows, counts, d

    def test_parked_car_is_flagged_once_with_a_position_and_a_reason(self):
        summary, rows, counts, d = self.run_pipeline(
            {"no_parking": {"polygon": [[100, 100], [500, 100], [500, 450],
                                        [100, 450]], "seconds": 2}},
            [[200, 200, 300, 300]], [2])

        self.assertEqual([r[0] for r in rows], ["illegal_parking"])
        self.assertEqual(rows[0][1], 500)
        self.assertAlmostEqual(rows[0][2], 0.391, places=2)
        self.assertAlmostEqual(rows[0][3], 0.625, places=2)
        self.assertEqual(dict(map(tuple, counts)), {"car": 1})
        self.assertTrue(Path(summary.violations[0]["evidence_path"]).exists())

    def test_a_bus_in_a_motorcycle_lane_is_flagged(self):
        summary, rows, _, _ = self.run_pipeline(
            {"restricted_lane": {"polygon": [[0, 0], [640, 0], [640, 480],
                                             [0, 480]],
                                 "allowed": ["motorcycle"]}},
            [[200, 200, 300, 300]], [5])

        self.assertEqual([r[0] for r in rows], ["wrong_lane"])

    def test_nothing_is_flagged_without_zones(self):
        _, rows, counts, _ = self.run_pipeline(
            {}, [[200, 200, 300, 300]], [2])

        self.assertEqual(rows, [])
        self.assertEqual(len(counts), 1)

    def test_emergency_wait_is_reported_from_the_signal_timer(self):
        from app.violation.signal import SignalSimulator

        class Ambulance:
            def detect(self, frame):
                return [{"bbox": (10, 10, 60, 60), "confidence": 0.9,
                         "class_name": "ambulance"}]

        from app.video_processor import TrafficVideoProcessor

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        patcher = mock.patch.object(vl, "DB_PATH", d / "t.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        video = d / "in.mp4"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"),
                                 10, (320, 240))

        if not writer.isOpened():
            self.skipTest("cannot write mp4v")

        for _ in range(20):
            writer.write(np.zeros((240, 320, 3), np.uint8))

        writer.release()
        processor = TrafficVideoProcessor(
            detector=mock.Mock(detect=lambda f: []),
            tracker=FakeTracker([[1, 1, 2, 2]], [2]),
            signal=SignalSimulator.cycle(20, 10), evidence_dir=d / "ev",
            emergency_detector=Ambulance())
        summary = processor.process(video, d / "o.mp4", show=False)
        wait = summary.emergency_events[0]["normal_wait_seconds"]

        # Confirmed at frame 3 (0.2 s in); red until 20 s.
        self.assertAlmostEqual(wait, 20 - 0.2, delta=1.0)

        with db_connect(d / "t.db") as conn:
            stored = conn.execute(
                "SELECT normal_wait_seconds FROM priority_events").fetchone()

        self.assertEqual(stored[0], wait)

    def test_unpredictable_signals_report_no_wait(self):
        from app.video_processor import TrafficVideoProcessor

        processor = TrafficVideoProcessor(
            detector=mock.Mock(), tracker=mock.Mock(),
            signal=AdaptiveSignal())

        self.assertIsNone(processor._normal_wait(1, 10))


class BulkReviewTests(unittest.TestCase):

    def test_each_record_is_decided_and_errors_are_collected(self):
        from app import audit, review

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.db"

            with mock.patch.object(vl, "DB_PATH", db), \
                    mock.patch.object(audit, "DB_PATH", db):
                evidence = Path(tmp) / "e.jpg"
                evidence.write_bytes(b"x")
                vl.log_violation("a", 1, "red_light", evidence)
                vl.log_violation("b", 2, "red_light", evidence)
                done, errors = review.set_many(
                    [1, 2, 999], review.APPROVED, "officer")

                with db_connect(db) as conn:
                    states = [r[0] for r in conn.execute(
                        "SELECT review_status FROM violation_records")]

        self.assertEqual(done, [1, 2])
        self.assertEqual([e[0] for e in errors], [999])
        self.assertEqual(states, ["approved", "approved"])


if __name__ == "__main__":
    unittest.main()
