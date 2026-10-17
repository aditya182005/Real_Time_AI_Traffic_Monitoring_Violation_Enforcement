import importlib
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from app import housekeeping
from app.ui import analytics
from tests.fake_streamlit import FakeStreamlit, install


def frame(**columns):
    return pd.DataFrame(columns)


NOW = pd.Timestamp("2026-10-17 12:00", tz="UTC")


def sample_data():
    return {
        "violations": frame(
            violation_type=["red_light", "speeding"],
            track_id=[4, 9], measured_speed=[None, 72.0],
            plate_text=["KA01AB1234", None],
            camera_id=["CAM-01", None], source=["a.mp4", "b.mp4"],
            fine_amount=[1000, 700],
            timestamp=[(NOW - pd.Timedelta(hours=2)).isoformat(),
                       (NOW - pd.Timedelta(hours=1)).isoformat()]),
        "collisions": frame(
            track_id_1=[1], track_id_2=[2], alert_status=["failed: 21608"],
            camera_id=["CAM-01"], source=["a.mp4"],
            timestamp=[NOW.isoformat()]),
        "priority": frame(
            vehicle_class=["ambulance"], confidence=[0.8765],
            camera_id=[None], source=["a.mp4"],
            timestamp=[(NOW - pd.Timedelta(hours=3)).isoformat()]),
        "density": frame(
            vehicle_count=[3.0, 9.0, 5.0], timestamp=[
                NOW.replace(hour=8).isoformat(), NOW.replace(hour=9).isoformat(),
                NOW.replace(hour=9).isoformat()]),
        "legacy_speed": pd.DataFrame(),
    }


def empty():
    return {key: pd.DataFrame() for key in sample_data()}


class RecentEventsTests(unittest.TestCase):

    def test_newest_first_with_useful_detail(self):
        table = analytics.recent_events(sample_data())

        self.assertEqual(list(table["Event"]), [
            "Possible collision", "Speeding", "Red light", "Emergency vehicle"])
        details = dict(zip(table["Event"], table["Detail"]))
        self.assertIn("72 km/h", details["Speeding"])
        self.assertIn("plate KA01AB1234", details["Red light"])
        self.assertIn("alert failed", details["Possible collision"])
        self.assertIn("0.88", details["Emergency vehicle"])

    def test_limit_and_empty(self):
        self.assertEqual(len(analytics.recent_events(sample_data(), 2)), 2)
        self.assertTrue(analytics.recent_events(empty()).empty)

    def test_where_prefers_camera_then_source(self):
        table = analytics.recent_events(sample_data())
        where = dict(zip(table["Event"], table["Where"]))

        self.assertEqual(where["Red light"], "CAM-01")
        self.assertEqual(where["Speeding"], "b.mp4")


class AttentionTests(unittest.TestCase):

    def test_failed_alerts_and_collisions_are_called_out(self):
        items = analytics.attention_items(sample_data(), True)
        kinds = [kind for kind, _ in items]

        self.assertEqual(kinds[0], "danger")
        self.assertIn("warn", kinds)
        self.assertNotIn("ok", kinds)

    def test_missing_twilio_is_noted_only_when_there_are_collisions(self):
        with_collision = analytics.attention_items(sample_data(), False)
        self.assertTrue(any("Twilio is not set up" in t
                            for _, t in with_collision))

        quiet = sample_data()
        quiet["collisions"] = pd.DataFrame()
        self.assertFalse(any("Twilio" in t for _, t in
                             analytics.attention_items(quiet, False)))

    def test_no_data_and_all_clear(self):
        self.assertIn("No records", analytics.attention_items(empty(), True)[0][1])

        calm = sample_data()
        calm["collisions"] = pd.DataFrame()
        self.assertEqual(analytics.attention_items(calm, True),
                         [("ok", "Nothing needs attention in this period.")])


class PeakHourTests(unittest.TestCase):

    def test_busiest_hour(self):
        self.assertEqual(analytics.peak_hour(sample_data()["density"]), (9, 7.0))

    def test_none_without_data(self):
        self.assertIsNone(analytics.peak_hour(pd.DataFrame()))


class FilterTests(unittest.TestCase):

    def setUp(self):
        self.addCleanup(install(FakeStreamlit()))
        self.filters = importlib.import_module("app.ui.filters")

    def test_presets(self):
        today = date(2026, 10, 17)

        self.assertEqual(self.filters.preset_range("Last 7 days", today),
                         (date(2026, 10, 10), today))
        self.assertEqual(self.filters.preset_range("Last 30 days", today)[0],
                         date(2026, 9, 17))
        self.assertEqual(self.filters.preset_range("All time", today)[0],
                         self.filters.EARLIEST)
        self.assertIsNone(self.filters.preset_range("Custom", today))

    def test_bar_defaults_to_thirty_days_and_asks_for_dates_only_for_custom(self):
        st = FakeStreamlit()
        self.addCleanup(install(st))
        filters = importlib.import_module("app.ui.filters")

        start, end = filters.date_range_bar()

        self.assertEqual((end - start).days, 30)
        self.assertEqual(st.called("date_input"), [])

    def test_custom_shows_the_date_pickers(self):
        st = FakeStreamlit(values={"Show records from": "Custom"})
        self.addCleanup(install(st))
        filters = importlib.import_module("app.ui.filters")

        filters.date_range_bar()

        self.assertEqual(len(st.called("date_input")), 2)


class DashboardLayoutTests(unittest.TestCase):

    def render(self, data):
        st = FakeStreamlit()
        self.addCleanup(install(st))
        importlib.import_module("app.ui.dashboard").render(
            data, date(2026, 1, 1), date(2026, 12, 31))

        return st

    def test_four_tabs_in_a_fixed_order(self):
        st = self.render(sample_data())
        labels = [c[1][0] for c in st.called("tabs")][0]

        self.assertEqual(labels, ["Overview", "Violations", "Traffic",
                                  "Alerts and priority"])

    def test_overview_has_the_attention_panel_and_latest_activity(self):
        st = self.render(sample_data())
        text = st.text()

        self.assertIn("Needs attention", text)
        self.assertIn("Latest activity", text)
        self.assertIn("Records from", text)

    def test_empty_database_still_renders_every_tab(self):
        st = self.render(empty())

        self.assertIn("No records in this period", st.text())
        self.assertIn("No traffic density data yet", st.text())


class StagingCleanupTests(unittest.TestCase):

    def test_only_old_session_folders_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "_staging"
            old, fresh, other = (staging / ("a" * 12), staging / ("b" * 12),
                                 staging / "keepme")

            for folder in (old, fresh, other):
                folder.mkdir(parents=True)
                (folder / "input.mp4").write_bytes(b"x")

            long_ago = time.time() - 3 * 86400

            import os
            os.utime(old, (long_ago, long_ago))
            os.utime(other, (long_ago, long_ago))

            removed = housekeeping.cleanup_staging(tmp)

            self.assertEqual(removed, ["a" * 12])
            self.assertTrue(fresh.exists())
            self.assertTrue(other.exists())

    def test_missing_folder_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(housekeeping.cleanup_staging(tmp), [])


class SessionStagingTests(unittest.TestCase):

    def staging_dir(self):
        st = FakeStreamlit()
        self.addCleanup(install(st))
        upload = importlib.import_module("app.ui.upload")

        return upload._staging_dir(), upload, st

    def test_each_session_gets_its_own_folder(self):
        first, upload, _ = self.staging_dir()
        second, _, _ = self.staging_dir()

        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, upload.STAGING_ROOT)

    def test_a_session_keeps_the_same_folder_between_reruns(self):
        first, upload, st = self.staging_dir()

        self.assertEqual(upload._staging_dir(), first)
        self.assertRegex(first.name, r"^[0-9a-f]{12}$")


if __name__ == "__main__":
    unittest.main()
