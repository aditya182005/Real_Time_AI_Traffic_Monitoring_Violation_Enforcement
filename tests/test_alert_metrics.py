import sqlite3

from tests.db_helpers import db_connect
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

from app.alerts import twilio_alert
from app.ui import analytics
from app.violation import violation_logger as vl


class TempDatabase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "t.db"
        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def latency(self, event_id):
        with db_connect(self.db) as conn:
            return conn.execute(
                "SELECT alert_status, alert_latency_ms "
                "FROM collision_events WHERE id = ?", (event_id,)
            ).fetchone()


class LatencyStorageTests(TempDatabase):

    def new_event(self):
        return vl.log_collision_event(1, 2, "e.jpg", alert_status="pending")

    def test_dispatch_records_detection_to_response_time(self):
        event = self.new_event()

        def slow_sender(message):
            time.sleep(0.05)
            return "sent"

        twilio_alert.dispatch(event, "hi", sync=True, sender=slow_sender)

        status, latency = self.latency(event)
        self.assertEqual(status, "sent")
        self.assertGreaterEqual(latency, 50)
        self.assertLess(latency, 5000)

    def test_failures_are_timed_too(self):
        event = self.new_event()

        def broken(message):
            raise RuntimeError("boom")

        twilio_alert.dispatch(event, "hi", sync=True, sender=broken)

        status, latency = self.latency(event)
        self.assertTrue(status.startswith("failed"))
        self.assertIsNotNone(latency)

    def test_status_without_latency_leaves_it_empty(self):
        event = self.new_event()
        vl.set_alert_status(event, "skipped (alerts off for this run)")

        self.assertIsNone(self.latency(event)[1])

    def test_old_databases_gain_the_column(self):
        with db_connect(self.db) as conn:
            conn.execute("""
                CREATE TABLE collision_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id_1 INTEGER NOT NULL,
                    track_id_2 INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    evidence_path TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO collision_events (track_id_1, track_id_2, "
                "event_type, timestamp, evidence_path) "
                "VALUES (1, 2, 'possible_collision', 't', 'e.jpg')")

        vl.setup_database()

        with db_connect(self.db) as conn:
            columns = {r[1] for r in
                       conn.execute("PRAGMA table_info(collision_events)")}
            rows = conn.execute(
                "SELECT COUNT(*) FROM collision_events").fetchone()[0]

        self.assertIn("alert_latency_ms", columns)
        self.assertEqual(rows, 1)          # existing data is kept


class MetricsTests(unittest.TestCase):

    def frame(self, rows):
        return pd.DataFrame(rows, columns=["alert_status",
                                           "alert_latency_ms"])

    def test_success_rate_ignores_skipped_and_pending(self):
        metrics = analytics.alert_metrics(self.frame([
            ("sent", 800.0),
            ("sent (sms and call)", 1200.0),
            ("failed: Twilio error 21608", 300.0),
            ("skipped (Twilio not configured)", None),
            ("pending", None),
        ]))

        self.assertEqual(metrics["attempted"], 3)
        self.assertAlmostEqual(metrics["success_rate"], 2 / 3)

    def test_latency_is_for_sent_alerts_only(self):
        metrics = analytics.alert_metrics(self.frame([
            ("sent", 800.0),
            ("sent", 1200.0),
            ("sent", 4000.0),
            ("failed: x", 99999.0),     # must not distort the figures
        ]))

        self.assertEqual(metrics["median_ms"], 1200.0)
        self.assertEqual(metrics["slowest_ms"], 4000.0)

    def test_nothing_attempted_gives_no_rate(self):
        metrics = analytics.alert_metrics(self.frame([
            ("skipped (alerts off for this run)", None)]))

        self.assertEqual(metrics["attempted"], 0)
        self.assertIsNone(metrics["success_rate"])
        self.assertIsNone(metrics["median_ms"])

    def test_empty_and_old_frames_do_not_crash(self):
        self.assertIsNone(
            analytics.alert_metrics(pd.DataFrame())["success_rate"])

        old = pd.DataFrame({"alert_status": ["sent"]})   # no latency column
        metrics = analytics.alert_metrics(old)
        self.assertEqual(metrics["success_rate"], 1.0)
        self.assertIsNone(metrics["median_ms"])


class AlertsPageTests(unittest.TestCase):

    def test_page_shows_the_new_figures(self):
        from tests.fake_streamlit import FakeStreamlit, install
        import importlib

        st = FakeStreamlit()
        restore = install(st)
        self.addCleanup(restore)

        data = {k: pd.DataFrame() for k in
                ("violations", "density", "priority", "collisions",
                 "legacy_speed")}
        data["collisions"] = pd.DataFrame({
            "timestamp": ["2026-10-11T10:00:00+00:00"],
            "alert_status": ["sent"],
            "alert_latency_ms": [1500.0],
        })

        importlib.import_module("app.ui.alerts").render(data)

        text = st.text()
        self.assertIn("Success rate", text)
        self.assertIn("100%", text)
        self.assertIn("1.5 s", text)


if __name__ == "__main__":
    unittest.main()
