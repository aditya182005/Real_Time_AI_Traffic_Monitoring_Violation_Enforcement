import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import footage_report as fr


def fake_summary(events=0, violations=()):
    return SimpleNamespace(
        frames=300, video_fps=30.0, processing_fps=5.0,
        emergency_events=[{"class_name": "ambulance", "confidence": 0.8,
                           "time_seconds": 2.0}] * events,
        violations=[{"type": v} for v in violations], collisions=[],
    )


class FootageReportTests(unittest.TestCase):
    def test_aggregate_counts_false_alarms_and_hits(self):
        rows = [
            fr.summarize_clip("a.mp4", "normal", fake_summary(0)),
            fr.summarize_clip("b.mp4", "normal", fake_summary(2)),
            fr.summarize_clip("c.mp4", "emergency", fake_summary(1)),
            fr.summarize_clip("d.mp4", "emergency", fake_summary(0)),
        ]
        totals = fr.aggregate(rows)

        self.assertEqual(totals["false_alarms"], 2)
        self.assertEqual(totals["normal_clips_with_false_alarm"], 1)
        self.assertEqual(totals["false_alarms_per_hour"], 360.0)  # 2 in 20 s
        self.assertEqual(totals["emergency_hit_rate"], 0.5)
        self.assertIn("false alarm", fr.to_markdown(rows, totals).lower())

    def test_no_clips_means_no_division_by_zero(self):
        totals = fr.aggregate([])

        self.assertIsNone(totals["false_alarms_per_hour"])
        self.assertIsNone(totals["emergency_hit_rate"])

    def test_main_runs_every_clip_and_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "n").mkdir()
            (tmp / "n" / "x.mp4").write_bytes(b"")
            (tmp / "n" / "notes.txt").write_text("skip me")
            seen = []

            def runner(argv):
                seen.append(argv)
                return fake_summary(1, ["speeding"])

            totals = fr.main(
                ["--normal", str(tmp / "n"), "--report", str(tmp / "r"),
                 "--", "--speed"], runner=runner)

            self.assertEqual(len(seen), 1)
            self.assertIn("--speed", seen[0])
            self.assertIn("--emergency", seen[0])
            self.assertEqual(totals["false_alarms"], 1)
            self.assertIn("speeding x1", (tmp / "r.md").read_text())
            self.assertTrue((tmp / "r.json").exists())


if __name__ == "__main__":
    unittest.main()
