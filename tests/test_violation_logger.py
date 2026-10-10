import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.violation import violation_logger as vl


class ViolationLoggerTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "test.db"
        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(
                "SELECT event_key, violation_type, fine_amount, evidence_path "
                "FROM violation_records ORDER BY id"
            ).fetchall()

    def test_table_is_created_on_first_log(self):
        # Regression: log_violation() used to crash with
        # "no such table: violation_records" unless setup_database() had
        # been called, which the red-light and speed pipelines never did.
        self.assertTrue(vl.log_violation(
            "k1", 7, "red_light", "ev.jpg", signal_state="RED"
        ))
        self.assertEqual(
            self.rows(), [("k1", "red_light", 1000, "ev.jpg")]
        )

    def test_duplicate_event_key_is_ignored(self):
        self.assertTrue(vl.log_violation("k1", 7, "red_light", "a.jpg"))
        self.assertFalse(vl.log_violation("k1", 7, "red_light", "a.jpg"))
        self.assertEqual(len(self.rows()), 1)

    def test_speeding_fine_scales_with_excess(self):
        self.assertEqual(vl.calculate_fine("speeding", 45, 40), 600)
        self.assertEqual(vl.calculate_fine("speeding", 50, 40), 600)
        self.assertEqual(vl.calculate_fine("speeding", 51, 40), 700)

    def test_no_record_when_not_speeding(self):
        self.assertFalse(vl.log_violation(
            "k2", 8, "speeding", "b.jpg", speed=40, speed_limit=40
        ))
        self.assertFalse(self.db.exists() and self.rows())

    def test_unknown_type_and_missing_speed_raise(self):
        with self.assertRaises(ValueError):
            vl.calculate_fine("parking")
        with self.assertRaises(ValueError):
            vl.calculate_fine("speeding")


if __name__ == "__main__":
    unittest.main()
