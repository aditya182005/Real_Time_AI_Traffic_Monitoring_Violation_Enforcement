import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.violation import violation_logger as vl


class LoggerExtrasTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "t.db"
        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def columns(self, table):
        with sqlite3.connect(self.db) as conn:
            return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}

    def test_wrong_way_has_a_demo_fine(self):
        self.assertEqual(vl.calculate_fine("wrong_way"), vl.WRONG_WAY_FINE)

    def test_camera_id_is_stored_on_violations(self):
        vl.log_violation("k", 1, "wrong_way", "e.jpg", camera_id="CAM-7")

        with sqlite3.connect(self.db) as conn:
            row = conn.execute(
                "SELECT camera_id, fine_amount FROM violation_records"
            ).fetchone()

        self.assertEqual(row, ("CAM-7", vl.WRONG_WAY_FINE))

    def test_collision_event_round_trip(self):
        event_id = vl.log_collision_event(
            3, 4, "e.jpg", camera_id="C", source="clip.mp4",
            crop_path="c.jpg", alert_status="pending",
        )
        vl.set_alert_status(event_id, "sent")

        with sqlite3.connect(self.db) as conn:
            row = conn.execute(
                "SELECT track_id_1, track_id_2, alert_status, camera_id, "
                "source, crop_path FROM collision_events"
            ).fetchone()

        self.assertEqual(row, (3, 4, "sent", "C", "clip.mp4", "c.jpg"))

    def test_priority_event_records_the_override(self):
        vl.log_priority_event("ambulance", 0.91, camera_id="C", source="s")

        with sqlite3.connect(self.db) as conn:
            row = conn.execute(
                "SELECT vehicle_class, signal_override, camera_id "
                "FROM priority_events"
            ).fetchone()

        self.assertEqual(row, ("ambulance", 1, "C"))

    def test_old_databases_are_migrated_without_losing_rows(self):
        # The schema as first released: none of the later columns exist.
        with sqlite3.connect(self.db) as conn:
            conn.execute("""CREATE TABLE violation_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE, track_id INTEGER NOT NULL,
                violation_type TEXT NOT NULL, measured_speed REAL,
                speed_limit REAL, signal_state TEXT,
                fine_amount INTEGER NOT NULL, timestamp TEXT NOT NULL,
                evidence_path TEXT)""")
            conn.execute("""CREATE TABLE collision_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id_1 INTEGER NOT NULL, track_id_2 INTEGER NOT NULL,
                event_type TEXT NOT NULL, timestamp TEXT NOT NULL,
                evidence_path TEXT NOT NULL)""")
            conn.execute(
                "INSERT INTO violation_records (event_key, track_id, "
                "violation_type, fine_amount, timestamp) "
                "VALUES ('old', 1, 'red_light', 1000, 't')")
            conn.commit()

        vl.setup_database()

        self.assertLessEqual(
            {"source", "crop_path", "camera_id"},
            self.columns("violation_records"),
        )
        self.assertLessEqual(
            {"alert_status", "camera_id", "source", "crop_path"},
            self.columns("collision_events"),
        )

        with sqlite3.connect(self.db) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM violation_records").fetchone()[0], 1
            )

        # And new writes work against the migrated tables.
        self.assertTrue(vl.log_violation("new", 2, "red_light", "e.jpg",
                                         camera_id="C"))
        self.assertIsInstance(vl.log_collision_event(1, 2, "e.jpg"), int)


if __name__ == "__main__":
    unittest.main()
