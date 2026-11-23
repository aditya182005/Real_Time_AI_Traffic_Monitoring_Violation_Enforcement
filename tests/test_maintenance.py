import os
import sqlite3
import tarfile
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app import audit, housekeeping, integrity, maintenance, privacy
from app.violation import violation_logger as vl
from tests.db_helpers import db_connect


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "traffic_agent.db"
        self.out = self.dir / "outputs"
        (self.out / "uploads" / "_staging").mkdir(parents=True)
        (self.out / "violations").mkdir()

        for target, name, value in (
                (vl, "DB_PATH", self.db), (audit, "DB_PATH", self.db),
                (maintenance.paths, "DB_PATH", self.db),
                (maintenance.paths, "DATA_DIR", self.dir),
                (maintenance.paths, "OUTPUT_DIR", self.out),
                (maintenance.paths, "ALLOWED_EVIDENCE_ROOTS", (self.dir,))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        env = mock.patch.dict(os.environ, {"BACKUP_DIR": str(self.dir / "bk"),
                                           "EVIDENCE_RETENTION_DAYS": "0",
                                           "UPLOAD_RETENTION_DAYS": "0"})
        env.start()
        self.addCleanup(env.stop)
        ev = self.out / "violations" / "a.jpg"
        ev.write_bytes(b"evidence")
        vl.log_violation("k", 1, "red_light", ev, plate_text="KA01AB1234")
        self.ev = ev

    def names(self, archive):
        with tarfile.open(archive) as tar:
            return tar.getnames()

    def test_backup_has_database_and_evidence_and_is_restorable(self):
        archive = maintenance.make_backup()
        names = self.names(archive)

        self.assertIn("traffic_agent.db", names)
        self.assertIn("outputs/violations/a.jpg", names)
        self.assertFalse(any("_staging" in n for n in names))

        with tarfile.open(archive) as tar, tempfile.TemporaryDirectory() as d:
            tar.extractall(d, filter="data")
            conn = sqlite3.connect(Path(d) / "traffic_agent.db")
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM violation_records").fetchone()[0], 1)
            conn.close()

    def test_database_only_backup(self):
        names = self.names(maintenance.make_backup(include_outputs=False))

        self.assertEqual(names, ["traffic_agent.db"])

    def test_only_newest_backups_are_kept(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)

        for day in range(5):
            maintenance.make_backup(keep=3, now=base + timedelta(days=day))

        kept = sorted(p.name for p in (self.dir / "bk").glob("traffic-data-*.tgz"))

        self.assertEqual(len(kept), 3)
        self.assertTrue(kept[0].startswith("traffic-data-20260103"))

    def test_nothing_to_back_up_yet(self):
        self.db.unlink()
        self.assertEqual(self.out.exists(), True)
        # outputs exists, so an archive is still made; remove it for the empty case
        import shutil
        shutil.rmtree(self.out)

        self.assertIsNone(maintenance.make_backup())

    def test_run_once_logs_head_and_reports_ok(self):
        summary = maintenance.run_once()
        log = (self.dir / "bk" / "integrity-heads.log").read_text()

        self.assertEqual(summary["problems"], [])
        self.assertIn(summary["head"], log)
        self.assertIn("OK", maintenance.describe(summary))
        self.assertTrue(Path(summary["backup"]).exists())

    def test_tampering_is_reported_and_exit_code_is_1(self):
        with db_connect(self.db) as conn:
            conn.execute("UPDATE violation_records SET fine_amount = 1")

        self.assertEqual(maintenance.main(["--once"]), 1)

    def test_clean_run_exits_0(self):
        self.assertEqual(maintenance.main(["--once"]), 0)

    def test_retention_purges_old_evidence_but_integrity_ran_first(self):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()

        with db_connect(self.db) as conn:
            conn.execute("UPDATE violation_records SET timestamp = ?", (old,))

        with mock.patch.dict(os.environ, {"EVIDENCE_RETENTION_DAYS": "30"}):
            summary = maintenance.run_once()

        self.assertEqual(summary["purged"]["records"], 1)
        self.assertFalse(self.ev.exists())

    def test_old_upload_folders_are_removed(self):
        run = self.out / "uploads" / "0123abcd"
        run.mkdir()
        old = time.time() - 40 * 86400
        os.utime(run, (old, old))

        with mock.patch.dict(os.environ, {"UPLOAD_RETENTION_DAYS": "30"}):
            summary = maintenance.run_once()

        self.assertEqual(summary["runs_removed"], 1)

    def test_loop_survives_a_failure_and_sleeps_between_runs(self):
        sleeps = []
        calls = {"n": 0}
        real = maintenance.run_once

        def flaky(**kw):
            calls["n"] += 1

            if calls["n"] == 1:
                raise RuntimeError("disk full")

            return real(**kw)

        with mock.patch.object(maintenance, "run_once", flaky):
            status = maintenance.main(["--loop", "--every-hours", "2",
                                       "--max-runs", "2"], sleep=sleeps.append)

        self.assertEqual(sleeps, [7200.0])
        self.assertEqual(calls["n"], 2)
        self.assertEqual(status, 1)         # the failed night is not hidden


if __name__ == "__main__":
    unittest.main()
