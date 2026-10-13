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

from app import plates
from app.violation import violation_logger as vl
from tests.db_helpers import db_connect
from tests.test_video_processor import FakeDetector, ScriptedTracker


class FakeReader:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def read(self, image):
        self.calls += 1

        return list(self.results[min(self.calls - 1, len(self.results) - 1)])


class NormalizeTests(unittest.TestCase):

    def test_keeps_only_letters_and_digits_in_upper_case(self):
        self.assertEqual(plates.normalize("ka 01-ab 1234"), "KA01AB1234")

    def test_rejects_things_that_cannot_be_a_plate(self):
        for text in ("", None, "AB", "ABCDEFGH", "A" * 11 + "1", "12"):
            self.assertIsNone(plates.normalize(text), text)

    def test_needs_at_least_one_digit(self):
        self.assertIsNone(plates.normalize("STOPSIGN"))


class IndianFormatTests(unittest.TestCase):

    def test_a_valid_plate_is_unchanged(self):
        self.assertEqual(plates.correct_indian("KA01AB1234"), "KA01AB1234")
        self.assertEqual(plates.correct_indian("MH12DE1433"), "MH12DE1433")

    def test_digit_confusions_in_letter_positions_are_fixed(self):
        # 0 for O in the state code, 1 for I in the series
        self.assertEqual(plates.correct_indian("KA01A81234"), "KA01AB1234")
        self.assertEqual(plates.correct_indian("K401AB1234"), None)

    def test_letter_confusions_in_digit_positions_are_fixed(self):
        self.assertEqual(plates.correct_indian("KAO1AB1234"), "KA01AB1234")
        self.assertEqual(plates.correct_indian("KA01ABI234"), "KA01AB1234")

    def test_too_many_changes_means_no_guess(self):
        self.assertIsNone(plates.correct_indian("5A8S1B12ZO"))

    def test_clean_plate_marks_whether_it_fits(self):
        self.assertEqual(plates.clean_plate("KA01AB1234", "IN"),
                         ("KA01AB1234", True))
        self.assertEqual(plates.clean_plate("ZZZZ99", "IN"),
                         ("ZZZZ99", False))
        self.assertEqual(plates.clean_plate("ZZZZ99", "ANY"),
                         ("ZZZZ99", True))
        self.assertIsNone(plates.clean_plate("!!", "IN"))

    def test_region_setting(self):
        with mock.patch.dict("os.environ", {"PLATE_REGION": "any"}):
            self.assertEqual(plates.region(), "ANY")

        with mock.patch.dict("os.environ", {"PLATE_REGION": "xx"}):
            self.assertEqual(plates.region(), "IN")


class VoteTests(unittest.TestCase):

    def test_the_text_most_reads_agree_on_wins(self):
        votes = plates.PlateVotes(plate_region="IN")
        votes.add(1, ("KA01AB1234", 0.6))
        votes.add(1, ("KA01AB1284", 0.9))   # one blurry misread
        votes.add(1, ("KA01AB1234", 0.7))

        text, confidence = votes.best(1)

        self.assertEqual(text, "KA01AB1234")
        self.assertAlmostEqual(confidence, 0.65)

    def test_nothing_readable_gives_none(self):
        votes = plates.PlateVotes()
        votes.add(1, None)
        votes.add(1, ("??", 0.9))

        self.assertIsNone(votes.best(1))
        self.assertIsNone(votes.best(99))

    def test_attempts_are_limited_even_when_reads_fail(self):
        votes = plates.PlateVotes(max_reads=2)

        self.assertTrue(votes.wants_more(1))
        votes.add(1, None)
        votes.add(1, None)
        self.assertFalse(votes.wants_more(1))
        self.assertTrue(votes.wants_more(2))

    def test_a_read_that_fits_the_format_beats_one_that_does_not(self):
        votes = plates.PlateVotes(plate_region="IN")
        votes.add(1, ("WXYZ99", 0.8))
        votes.add(1, ("KA01AB1234", 0.6))

        self.assertEqual(votes.best(1)[0], "KA01AB1234")


class ReadPlateTests(unittest.TestCase):

    def crop(self):
        return np.zeros((100, 200, 3), np.uint8)

    def test_reads_the_best_candidate(self):
        reader = FakeReader([("junk", 0.99), ("KA01AB1234", 0.8)])

        self.assertEqual(plates.read_plate(reader, self.crop()),
                         ("KA01AB1234", 0.8))

    def test_without_a_locator_only_the_lower_part_is_read(self):
        seen = []

        class Spy:
            def read(self, image):
                seen.append(image.shape)
                return []

        plates.read_plate(Spy(), self.crop())

        self.assertEqual(seen[0][0], 55)

    def test_locator_boxes_are_used(self):
        seen = []

        class Spy:
            def read(self, image):
                seen.append(image.shape[:2])
                return [("KA01AB1234", 0.9)]

        result = plates.read_plate(
            Spy(), self.crop(), locator=lambda crop: [(10, 20, 110, 60)])

        self.assertEqual(seen, [(40, 100)])
        self.assertEqual(result[0], "KA01AB1234")

    def test_two_row_plates_are_joined(self):
        reader = FakeReader([("KA01", 0.9), ("AB1234", 0.8)])

        self.assertEqual(plates.read_plate(reader, self.crop())[0],
                         "KA01AB1234")

    def test_empty_inputs(self):
        reader = FakeReader([("KA01AB1234", 0.9)])

        self.assertIsNone(plates.read_plate(reader, None))
        self.assertIsNone(plates.read_plate(reader, np.empty((0, 0, 3))))
        self.assertEqual(reader.calls, 0)
        self.assertIsNone(plates.read_plate(FakeReader([]), self.crop()))


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class PrepareTests(unittest.TestCase):

    def test_small_images_are_enlarged_and_greyed(self):
        out = plates.prepare_for_ocr(np.zeros((20, 60, 3), np.uint8))

        self.assertEqual(out.ndim, 2)
        self.assertGreaterEqual(out.shape[1], 240)


class AvailabilityTests(unittest.TestCase):

    def test_switch_off_with_environment(self):
        with mock.patch.dict("os.environ", {"PLATE_OCR": "off"}):
            self.assertFalse(plates.reader_available())

    def test_detector_weights_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(plates.PlateDetector.available(
                Path(tmp) / "none.pt"))


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class PipelineTests(unittest.TestCase):

    BOTTOMS = [None, None, 100, 140, 180, 220, 260, 300, 340]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.video = self.dir / "in.mp4"
        writer = cv2.VideoWriter(
            str(self.video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 400))

        if not writer.isOpened():
            self.skipTest("this OpenCV build cannot write mp4v video")

        for _ in self.BOTTOMS:
            writer.write(np.zeros((400, 160, 3), np.uint8))

        writer.release()

    def run_pipeline(self, reader, save=True, **options):
        from app.video_processor import TrafficVideoProcessor

        processor = TrafficVideoProcessor(
            detector=FakeDetector(),
            tracker=ScriptedTracker(self.BOTTOMS),
            stop_line_y=250,
            signal_state="RED",
            evidence_dir=self.dir / "evidence",
            plate_reader=reader,
            plate_min_height=10,
            plate_every=1,
            **options,
        )

        return processor.process(
            self.video, self.dir / "out.mp4", show=False, save_to_db=save)

    def stored(self):
        with db_connect(self.db) as conn:
            return conn.execute(
                "SELECT plate_text, plate_confidence "
                "FROM violation_records").fetchall()

    def test_plate_is_saved_with_the_violation(self):
        summary = self.run_pipeline(FakeReader([("KA01AB1234", 0.9)]))

        self.assertEqual(summary.violations[0]["plate_text"], "KA01AB1234")
        self.assertEqual(self.stored(), [("KA01AB1234", 0.9)])

    def test_no_reader_means_no_plate(self):
        summary = self.run_pipeline(None)

        self.assertIsNone(summary.violations[0]["plate_text"])
        self.assertEqual(self.stored(), [(None, None)])

    def test_unreadable_plate_is_stored_empty_not_guessed(self):
        summary = self.run_pipeline(FakeReader([("??", 0.9)]))

        self.assertEqual(len(summary.violations), 1)
        self.assertIsNone(summary.violations[0]["plate_text"])

    def test_a_crashing_reader_never_stops_the_analysis(self):
        class Broken:
            def read(self, image):
                raise RuntimeError("OCR exploded")

        summary = self.run_pipeline(Broken())

        self.assertEqual(len(summary.violations), 1)
        self.assertIsNone(summary.violations[0]["plate_text"])

    def test_each_vehicle_is_read_a_limited_number_of_times(self):
        reader = FakeReader([("??", 0.9)])
        self.run_pipeline(reader)

        self.assertLessEqual(reader.calls, 4)   # 3 samples + 1 at the event

    def test_old_databases_gain_the_columns(self):
        with db_connect(self.db) as conn:
            conn.execute("""CREATE TABLE violation_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE, track_id INTEGER NOT NULL,
                violation_type TEXT NOT NULL, measured_speed REAL,
                speed_limit REAL, signal_state TEXT,
                fine_amount INTEGER NOT NULL, timestamp TEXT NOT NULL,
                evidence_path TEXT)""")

        vl.log_violation("k1", 1, "red_light", "x.jpg",
                         plate_text="KA01AB1234", plate_confidence=0.5)

        self.assertEqual(self.stored(), [("KA01AB1234", 0.5)])


if __name__ == "__main__":
    unittest.main()
