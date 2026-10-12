import contextlib
import io
import json
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

import evaluate
import run_video
from tests.test_run_video_cli import CarMovingDown, FakeDetector


class LoadTruthTests(unittest.TestCase):

    def load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truth.csv"
            path.write_text(text, encoding="utf-8")

            return evaluate.load_truth(path)

    def test_reads_events_and_ignores_blank_lines(self):
        events = self.load(
            "type,time_seconds\nred_light,12.4\n\n collision , 48 \n")

        self.assertEqual(events, [("red_light", 12.4), ("collision", 48.0)])

    def test_accepts_a_byte_order_mark(self):
        events = self.load("﻿type,time_seconds\nspeeding,3\n")

        self.assertEqual(events, [("speeding", 3.0)])

    def test_missing_columns_are_explained(self):
        with self.assertRaisesRegex(ValueError, "type,time_seconds"):
            self.load("kind,when\nred_light,1\n")

    def test_unknown_type_names_the_line(self):
        with self.assertRaisesRegex(ValueError, "Line 3.*'jaywalking'"):
            self.load("type,time_seconds\nred_light,1\njaywalking,2\n")

    def test_bad_and_negative_times_name_the_line(self):
        with self.assertRaisesRegex(ValueError, "Line 2.*number"):
            self.load("type,time_seconds\nred_light,soon\n")

        with self.assertRaisesRegex(ValueError, "Line 2.*negative"):
            self.load("type,time_seconds\nred_light,-1\n")


class MatchTests(unittest.TestCase):

    def test_exact_and_near_matches_count(self):
        self.assertEqual(
            evaluate.match_times([10.0, 20.5], [10.2, 20.0], 1.0), (2, 0, 0))

    def test_outside_the_window_is_false_and_missed(self):
        self.assertEqual(evaluate.match_times([5.0], [10.0], 1.0), (0, 1, 1))

    def test_one_detection_cannot_match_two_events(self):
        tp, fp, fn = evaluate.match_times([10.0], [9.8, 10.2], 1.0)

        self.assertEqual((tp, fp, fn), (1, 0, 1))

    def test_nothing_on_either_side(self):
        self.assertEqual(evaluate.match_times([], [], 1.0), (0, 0, 0))

    def test_closest_candidate_is_used(self):
        # 10.9 is within the window of 10.0 but 10.1 is closer, so 10.9 is
        # left over rather than stealing the match.
        self.assertEqual(
            evaluate.match_times([10.9, 10.1], [10.0], 1.0), (1, 1, 0))


class ScoreTests(unittest.TestCase):

    def test_per_type_and_overall_numbers(self):
        predictions = [("red_light", 10.0), ("red_light", 30.0),
                       ("speeding", 5.0)]
        truth = [("red_light", 10.1), ("red_light", 50.0),
                 ("speeding", 5.2)]

        result = evaluate.score(predictions, truth, 1.0)

        red = result["by_type"]["red_light"]
        self.assertEqual((red["tp"], red["fp"], red["fn"]), (1, 1, 1))
        self.assertAlmostEqual(red["precision"], 0.5)
        self.assertAlmostEqual(red["recall"], 0.5)
        self.assertAlmostEqual(red["f1"], 0.5)
        self.assertEqual(result["by_type"]["speeding"]["f1"], 1.0)

        overall = result["overall"]
        self.assertEqual((overall["tp"], overall["fp"], overall["fn"]),
                         (2, 1, 1))
        self.assertAlmostEqual(overall["precision"], 2 / 3)
        self.assertAlmostEqual(overall["recall"], 2 / 3)

    def test_types_that_are_not_checked_are_left_out(self):
        result = evaluate.score(
            [], [("collision", 5.0)], 1.0, checked=["red_light"])

        self.assertEqual(result["by_type"], {})
        self.assertEqual(result["overall"]["fn"], 0)

    def test_no_events_at_all_gives_no_percentages(self):
        overall = evaluate.score([], [], 1.0)["overall"]

        self.assertIsNone(overall["precision"])
        self.assertIsNone(overall["recall"])
        self.assertIsNone(overall["f1"])

    def test_only_false_alarms_gives_zero_f1(self):
        overall = evaluate.score(
            [("red_light", 1.0)], [], 1.0)["overall"]

        self.assertEqual(overall["precision"], 0.0)
        self.assertIsNone(overall["recall"])
        self.assertEqual(overall["f1"], 0.0)


class PredictionTests(unittest.TestCase):

    def test_violations_and_collisions_are_merged(self):
        summary = SimpleNamespace(
            violations=[{"type": "red_light", "time_seconds": 1.5}],
            collisions=[{"time_seconds": 4}],
        )

        self.assertEqual(
            evaluate.predictions_from_summary(summary),
            [("red_light", 1.5), ("collision", 4.0)])


class EnabledTypesTests(unittest.TestCase):

    def test_follows_the_chosen_checks(self):
        parse = evaluate.build_parser().parse_args

        self.assertEqual(
            evaluate.enabled_types(parse(["--truth", "t.csv"])),
            ["red_light"])
        self.assertEqual(
            evaluate.enabled_types(parse(
                ["--truth", "t.csv", "--speed", "--wrong-way",
                 "--collisions"])),
            ["red_light", "speeding", "wrong_way", "collision"])


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class MainTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

        patcher = mock.patch.object(
            run_video, "OUTPUT_DIR", self.dir / "outputs")
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

    def write_truth(self, text):
        path = self.dir / "truth.csv"
        path.write_text(text, encoding="utf-8")

        return path

    def run_eval(self, truth_text, *extra):
        truth = self.write_truth(truth_text)
        argv = ["--video", str(self.video), "--truth", str(truth),
                "--output", str(self.dir / "out.mp4"), *extra]
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            result = evaluate.main(
                argv, detector=FakeDetector(), tracker=CarMovingDown())

        return result, out.getvalue()

    def detected_time(self):
        # When does the pipeline say the car ran the light?
        with contextlib.redirect_stdout(io.StringIO()):
            summary = run_video.main(
                ["--input", str(self.video), "--output",
                 str(self.dir / "probe.mp4"), "--no-display", "--no-save"],
                detector=FakeDetector(), tracker=CarMovingDown())

        return summary.violations[0]["time_seconds"]

    def test_a_labelled_violation_is_found(self):
        moment = self.detected_time()

        result, output = self.run_eval(
            f"type,time_seconds\nred_light,{moment}\n")

        self.assertEqual(result["overall"]["tp"], 1)
        self.assertEqual(result["overall"]["fp"], 0)
        self.assertEqual(result["overall"]["f1"], 1.0)
        self.assertIn("OVERALL", output)
        self.assertIn("frames per second", output)

    def test_a_label_far_from_the_detection_counts_both_ways(self):
        moment = self.detected_time()

        result, _ = self.run_eval(
            f"type,time_seconds\nred_light,{moment + 30}\n")

        overall = result["overall"]
        self.assertEqual((overall["tp"], overall["fp"], overall["fn"]),
                         (0, 1, 1))

    def test_labels_for_checks_that_are_off_are_reported_not_scored(self):
        moment = self.detected_time()

        result, output = self.run_eval(
            f"type,time_seconds\nred_light,{moment}\ncollision,2\n")

        self.assertNotIn("collision", result["by_type"])
        self.assertEqual(result["overall"]["fn"], 0)
        self.assertIn("Not scored: 1 labelled collision", output)

    def test_it_never_writes_to_the_database(self):
        moment = self.detected_time()
        db = self.dir / "t.db"

        with mock.patch.object(
                run_video.paths, "DB_PATH", db), \
                mock.patch("app.violation.violation_logger.DB_PATH", db):
            self.run_eval(f"type,time_seconds\nred_light,{moment}\n")

        self.assertFalse(db.exists())

    def test_report_file_is_written(self):
        moment = self.detected_time()
        report = self.dir / "report.json"

        self.run_eval(f"type,time_seconds\nred_light,{moment}\n",
                      "--report", str(report))

        data = json.loads(report.read_text())
        self.assertEqual(data["overall"]["tp"], 1)
        self.assertEqual(data["tolerance_seconds"], 1.0)
        self.assertEqual(data["frames"], 9)
        self.assertIn("processing_fps", data)

    def test_bad_truth_file_stops_before_analysis(self):
        truth = self.write_truth("type,time_seconds\nflying,1\n")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit), \
                mock.patch.object(run_video, "run") as run:
            evaluate.main(["--video", str(self.video), "--truth",
                           str(truth)])

        self.assertIn("type must be one of", stderr.getvalue())
        run.assert_not_called()

    def test_missing_truth_file_is_a_clean_error(self):
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit):
            evaluate.main(["--truth", str(self.dir / "nope.csv")])

        self.assertIn("nope.csv", stderr.getvalue())

    def test_negative_tolerance_is_rejected(self):
        truth = self.write_truth("type,time_seconds\nred_light,1\n")
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit):
            evaluate.main(["--truth", str(truth), "--tolerance", "-1"])

        self.assertIn("--tolerance", stderr.getvalue())

    def test_truth_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            evaluate.main(["--video", str(self.video)])


if __name__ == "__main__":
    unittest.main()
