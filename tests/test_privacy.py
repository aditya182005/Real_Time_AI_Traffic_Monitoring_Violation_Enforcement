import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app import audit, integrity, privacy
from app.violation import violation_logger as vl
from tests.db_helpers import db_connect


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "t.db"

        for target, name, value in (
                (vl, "DB_PATH", self.db), (audit, "DB_PATH", self.db),
                (privacy.paths, "DB_PATH", self.db),
                (privacy.paths, "ALLOWED_EVIDENCE_ROOTS", (self.dir,))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.a = self.add("a", "KA01AB1234")
        self.b = self.add("b", "MH12XY9999")

    def add(self, key, plate):
        ev, crop = self.dir / f"{key}.jpg", self.dir / f"{key}_c.jpg"
        ev.write_bytes(b"x" + key.encode())
        crop.write_bytes(b"y" + key.encode())
        vl.log_violation(key, 1, "red_light", ev, crop_path=crop, plate_text=plate)

        return ev, crop

    def age(self, key, days):
        stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        with db_connect(self.db) as conn:
            conn.execute("UPDATE violation_records SET timestamp = ? "
                         "WHERE event_key = ?", (stamp, key))

    def plate(self, key):
        with db_connect(self.db) as conn:
            return conn.execute("SELECT plate_text FROM violation_records "
                                "WHERE event_key = ?", (key,)).fetchone()[0]

    def test_purge_removes_only_old_evidence_and_plate(self):
        self.age("a", 100)
        result = privacy.purge_old(90)

        self.assertEqual(result, {"records": 1, "files": 2})
        self.assertFalse(self.a[0].exists() or self.a[1].exists())
        self.assertTrue(self.b[0].exists())
        self.assertIsNone(self.plate("a"))
        self.assertEqual(self.plate("b"), "MH12XY9999")

    def test_dry_run_and_zero_days_change_nothing(self):
        self.age("a", 100)

        self.assertEqual(privacy.purge_old(90, dry_run=True)["records"], 1)
        self.assertEqual(privacy.purge_old(0), {"records": 0, "files": 0})
        self.assertTrue(self.a[0].exists())
        self.assertEqual(self.plate("a"), "KA01AB1234")

    def test_purged_images_are_warnings_not_tampering(self):
        # Move "now" forward rather than editing timestamps, which are
        # part of the sealed record.
        later = datetime.now(timezone.utc) + timedelta(days=100)
        privacy.purge_old(90, now=later)

        with db_connect(self.db) as conn:
            result = integrity.verify(conn)

        self.assertEqual(result["problems"], [])
        self.assertEqual(len(result["warnings"]), 4)  # both records, both files

    def test_erase_and_export_match_loosely_formatted_plates(self):
        exported = privacy.export_plate("ka 01-ab 1234")
        self.assertEqual(len(exported), 1)

        result = privacy.erase_plate("KA01AB1234")
        self.assertEqual(result, {"records": 1, "files": 2})
        self.assertIsNone(self.plate("a"))
        self.assertFalse(self.a[0].exists())
        self.assertTrue(self.b[0].exists())
        # The plate is not written to the audit log.
        self.assertNotIn("KA01", str(audit.recent(5)))

    def test_files_outside_allowed_folders_are_never_deleted(self):
        outside = Path(tempfile.mkdtemp()) / "keep.jpg"
        outside.write_bytes(b"z")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))

        with db_connect(self.db) as conn:
            conn.execute("UPDATE violation_records SET evidence_path = ? "
                         "WHERE event_key = 'a'", (str(outside),))

        privacy.erase_plate("KA01AB1234")
        self.assertTrue(outside.exists())

    def test_cli(self):
        self.age("a", 100)
        self.assertEqual(privacy.main(["purge", "--days", "90", "--dry-run"]), 0)
        self.assertEqual(privacy.main(["purge"]), 0)  # no setting: nothing to do
        self.assertTrue(self.a[0].exists())

        with self.assertRaises(ValueError):
            privacy.export_plate("---")

    def test_retention_setting_parsing(self):
        with mock.patch.dict("os.environ", {"EVIDENCE_RETENTION_DAYS": "30"}):
            self.assertEqual(privacy.retention_days(), 30)

        with mock.patch.dict("os.environ", {"EVIDENCE_RETENTION_DAYS": "x"}):
            self.assertEqual(privacy.retention_days(), 0)


if __name__ == "__main__":
    unittest.main()
