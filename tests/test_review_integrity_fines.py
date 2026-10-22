import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import audit, fines, integrity, review
from app.violation import violation_logger as vl
from tests.db_helpers import db_connect


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        for target in (vl, audit):
            patcher = mock.patch.object(target, "DB_PATH", self.db)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.files = []

    def evidence(self, name, content=b"frame"):
        path = self.dir / name
        path.write_bytes(content)
        return path

    def log(self, key, kind="red_light", **kw):
        ev = self.evidence(f"{key}.jpg", key.encode())
        crop = self.evidence(f"{key}_crop.jpg", key.encode() + b"c")
        self.assertTrue(vl.log_violation(
            key, 1, kind, ev, crop_path=crop, camera_id="C1", **kw))
        return ev, crop

    def verify(self, **kw):
        with db_connect(self.db) as conn:
            return integrity.verify(conn, **kw)


class FineTests(unittest.TestCase):
    def test_defaults_match_demo_values(self):
        with mock.patch.dict("os.environ", {"FINES_FILE": ""}):
            self.assertEqual(vl.calculate_fine("red_light"), 1000)
            self.assertEqual(vl.calculate_fine("speeding", 51, 40), 700)

    def test_file_overrides_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "f.json"
            f.write_text(json.dumps(
                {"red_light": 2000, "speeding": {"base": 100}}))

            with mock.patch.dict("os.environ", {"FINES_FILE": str(f)}):
                self.assertEqual(vl.calculate_fine("red_light"), 2000)
                self.assertEqual(vl.calculate_fine("wrong_way"), 1500)
                # base 100 + 2 blocks of the default 100
                self.assertEqual(vl.calculate_fine("speeding", 55, 40), 300)

    def test_bad_files_are_refused(self):
        for bad in ({"red_light": -1}, {"red_light": "10"}, {"parking": 5},
                    {"speeding": {"x": 1}}, [1]):
            with self.assertRaises(fines.FineConfigError):
                fines.parse(bad)

        with self.assertRaises(fines.FineConfigError):
            fines.load(Path("/nonexistent/fines.json"))


class IntegrityTests(Base):
    def test_clean_chain_verifies(self):
        self.log("a")
        self.log("b", "speeding", speed=60, speed_limit=40)
        result = self.verify()

        self.assertEqual(result["sealed"], 2)
        self.assertEqual(result["problems"], [])
        self.assertTrue(result["head"])

    def test_changed_field_is_detected(self):
        self.log("a")
        self.log("b")

        with db_connect(self.db) as conn:
            conn.execute("UPDATE violation_records SET fine_amount = 1 WHERE event_key = 'a'")

        kinds = {p[1] for p in self.verify()["problems"]}
        self.assertIn("record_changed", kinds)

    def test_deleted_middle_record_breaks_chain(self):
        for key in "abc":
            self.log(key)

        with db_connect(self.db) as conn:
            conn.execute("DELETE FROM violation_records WHERE event_key = 'b'")

        kinds = {p[1] for p in self.verify()["problems"]}
        self.assertIn("chain_broken", kinds)

    def test_swapped_evidence_is_detected_but_missing_is_only_a_warning(self):
        ev, crop = self.log("a")
        ev.write_bytes(b"different picture")
        crop.unlink()
        result = self.verify()

        self.assertEqual([p[1] for p in result["problems"]], ["evidence_changed"])
        self.assertEqual([w[1] for w in result["warnings"]], ["crop_missing"])

    def test_plate_and_review_changes_do_not_break_the_chain(self):
        self.log("a", plate_text="KA01AB1234")

        with db_connect(self.db) as conn:
            conn.execute("UPDATE violation_records SET plate_text = NULL")

        review.set_status(1, "approved", "alice")
        self.assertEqual(self.verify()["problems"], [])

    def test_speed_int_and_float_hash_the_same(self):
        self.log("a", "speeding", speed=60, speed_limit=40)
        self.assertEqual(self.verify()["problems"], [])

    def test_old_unsealed_records_are_counted_not_flagged(self):
        vl.setup_database()

        with db_connect(self.db) as conn:
            conn.execute(
                "INSERT INTO violation_records (event_key, track_id, "
                "violation_type, fine_amount, timestamp) "
                "VALUES ('old', 1, 'red_light', 1000, 't')")

        self.log("a")
        result = self.verify()

        self.assertEqual((result["sealed"], result["unsealed"]), (1, 1))
        self.assertEqual(result["problems"], [])

    def test_cli_reports_failure_and_expect(self):
        self.log("a")
        head = self.verify()["head"]

        with mock.patch.object(integrity.paths, "DB_PATH", self.db):
            self.assertEqual(integrity.main(["verify", "--expect", head]), 0)
            self.assertEqual(integrity.main(["verify", "--expect", "0" * 64]), 1)

            with db_connect(self.db) as conn:
                conn.execute("UPDATE violation_records SET camera_id = 'X'")

            self.assertEqual(integrity.main(["verify"]), 1)


class ReviewTests(Base):
    def test_new_records_are_pending_then_approved_with_audit(self):
        self.log("a")

        with db_connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT review_status FROM violation_records").fetchone()[0], "pending")

        review.set_status(1, "approved", "alice", "operator", note="clear")

        with db_connect(self.db) as conn:
            row = conn.execute(
                "SELECT review_status, reviewed_by, review_note "
                "FROM violation_records").fetchone()

        self.assertEqual(row, ("approved", "alice", "clear"))
        self.assertEqual(audit.recent(5)[0]["action"], "review_approved")

    def test_unknown_record_and_status_are_errors(self):
        vl.setup_database()

        with self.assertRaises(review.ReviewError):
            review.set_status(99, "approved", "alice")

        with self.assertRaises(review.ReviewError):
            review.set_status(1, "maybe", "alice")

        with self.assertRaises(review.ReviewError):
            review.set_status(1, "approved", "")

    def test_counts_treat_missing_status_as_pending(self):
        df = pd.DataFrame({"review_status": [None, "approved", "rejected", "pending"]})
        self.assertEqual(review.counts(df),
                         {"pending": 2, "approved": 1, "rejected": 1})
        self.assertEqual(review.counts(pd.DataFrame())["pending"], 0)
        self.assertEqual(review.counts(pd.DataFrame({"x": [1, 2]}))["pending"], 2)


if __name__ == "__main__":
    unittest.main()
