import unittest
from datetime import date

import pandas as pd

from app.ui import analytics


def frame(*timestamps, **extra):
    data = {"timestamp": list(timestamps)}
    data.update(extra)
    return pd.DataFrame(data)


class AnalyticsTests(unittest.TestCase):

    def test_filter_by_date_includes_whole_end_day(self):
        df = frame(
            "2026-10-09T23:59:59+00:00",
            "2026-10-10T00:00:00+00:00",
            "2026-10-10T23:59:59+00:00",
            "2026-10-11T00:00:00+00:00",
        )

        kept = analytics.filter_by_date(df, date(2026, 10, 10), date(2026, 10, 10))

        self.assertEqual(len(kept), 2)

    def test_filter_handles_empty_and_missing_column(self):
        self.assertTrue(analytics.filter_by_date(
            pd.DataFrame(), date(2026, 1, 1), date(2026, 1, 2)).empty)
        no_ts = pd.DataFrame({"a": [1]})
        self.assertEqual(len(analytics.filter_by_date(
            no_ts, date(2026, 1, 1), date(2026, 1, 2))), 1)

    def test_violations_per_hour_has_24_rows(self):
        df = frame(
            "2026-10-10T08:05:00+00:00",
            "2026-10-10T08:50:00+00:00",
            "2026-10-10T17:00:00+00:00",
        )

        table = analytics.violations_per_hour(df)

        self.assertEqual(len(table), 24)
        self.assertEqual(int(table.loc[8, "Violations"]), 2)
        self.assertEqual(int(table.loc[17, "Violations"]), 1)
        self.assertEqual(int(table["Violations"].sum()), 3)

    def test_violations_per_hour_empty(self):
        table = analytics.violations_per_hour(pd.DataFrame())
        self.assertEqual(len(table), 24)
        self.assertEqual(int(table["Violations"].sum()), 0)

    def test_density_by_hour_averages(self):
        df = frame(
            "2026-10-10T09:00:00+00:00",
            "2026-10-10T09:30:00+00:00",
            vehicle_count=[4, 6],
        )

        table = analytics.density_by_hour(df)

        self.assertEqual(table.loc[9, "Avg vehicles in view"], 5.0)
        self.assertEqual(table.loc[10, "Avg vehicles in view"], 0.0)

    def test_total_fines_and_by_type(self):
        df = pd.DataFrame({
            "violation_type": ["red_light", "speeding", "red_light"],
            "fine_amount": [1000, 800, 1000],
        })

        self.assertEqual(analytics.total_fines(df), 2800)
        self.assertEqual(len(analytics.by_type(df, "red_light")), 2)
        counts = analytics.violations_by_type(df)
        self.assertEqual(counts.iloc[0]["Count"], 2)

    def test_alert_status_counts(self):
        df = pd.DataFrame({"alert_status": [
            "sent", "skipped (Twilio not configured)",
            "failed: TwilioRestException", None, "pending",
        ]})

        self.assertEqual(
            analytics.alert_status_counts(df),
            {"sent": 1, "skipped": 1, "failed": 1, "pending": 2},
        )

    def test_latest_row(self):
        df = frame("2026-10-10T08:00:00+00:00", "2026-10-10T09:00:00+00:00",
                   name=["old", "new"])

        self.assertEqual(analytics.latest_row(df)["name"], "new")
        self.assertIsNone(analytics.latest_row(pd.DataFrame()))


if __name__ == "__main__":
    unittest.main()
