import importlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import housekeeping
from tests.fake_streamlit import FakeStreamlit, StopPage, install


class MainIsGatedTests(unittest.TestCase):
    """The gate must actually be wired into main.py, before any page."""

    def run_main(self, env, state=None, **kwargs):
        import sys

        st = FakeStreamlit(**kwargs)
        st.session_state.update(state or {})
        self.addCleanup(install(st))

        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("app.ui.data.load_all", create=True):
            sys.modules.pop("app.main", None)

            try:
                importlib.import_module("app.main")
            except StopPage:
                pass

        return st

    def test_no_page_is_shown_to_someone_not_signed_in(self):
        st = self.run_main({"DASHBOARD_PASSWORD": "s3cret"})
        text = st.text()

        self.assertIn("Enter the dashboard password", text)
        self.assertNotIn("Upload traffic photos", text)
        self.assertNotIn("Academic prototype", text)

    def test_signed_in_user_reaches_the_app(self):
        st = self.run_main({"DASHBOARD_PASSWORD": "s3cret"},
                           state={"user": {"name": "shared", "role": "operator"},
                                  "authenticated": True},
                           values={"Go to": "Analyze footage"})

        self.assertIn("Upload traffic photos", st.text())

    def test_production_without_password_shows_nothing(self):
        st = self.run_main({"APP_ENV": "production"})

        self.assertIn("DASHBOARD_PASSWORD is not set", st.text())
        self.assertNotIn("Upload traffic photos", st.text())


class RetentionSettingTests(unittest.TestCase):

    def test_default_keeps_everything(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(housekeeping.retention_days(), 0)

    def test_value_is_read_and_bad_values_mean_keep(self):
        for value, expected in (("30", 30), ("0", 0), ("-5", 0),
                                ("soon", 0), ("", 0)):
            with mock.patch.dict(
                    os.environ, {"UPLOAD_RETENTION_DAYS": value}, clear=True):
                self.assertEqual(housekeeping.retention_days(), expected,
                                 value)


class CleanupTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def folder(self, name, age_days):
        path = self.root / name
        path.mkdir()
        (path / "evidence.jpg").write_bytes(b"x")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))

        return path

    def test_old_run_folders_are_removed_and_new_ones_kept(self):
        old = self.folder("aaaaaaaa", 40)
        new = self.folder("bbbbbbbb", 2)

        removed = housekeeping.cleanup_old_runs(self.root, 30)

        self.assertEqual(removed, ["aaaaaaaa"])
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_disabled_when_retention_is_zero(self):
        old = self.folder("aaaaaaaa", 400)

        self.assertEqual(housekeeping.cleanup_old_runs(self.root, 0), [])
        self.assertTrue(old.exists())

    def test_only_folders_named_like_runs_are_touched(self):
        staging = self.folder("_staging", 400)
        other = self.folder("my-photos", 400)
        too_long = self.folder("aaaaaaaaaa", 400)
        upper = self.folder("AAAAAAAA", 400)
        (self.root / "loose.mp4").write_bytes(b"x")

        self.assertEqual(housekeeping.cleanup_old_runs(self.root, 1), [])

        for kept in (staging, other, too_long, upper,
                     self.root / "loose.mp4"):
            self.assertTrue(kept.exists(), kept.name)

    def test_symlinks_are_never_followed(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            target = Path(elsewhere)
            (target / "precious.txt").write_text("keep me")
            old = time.time() - 100 * 86400
            os.utime(target, (old, old))
            link = self.root / "cccccccc"

            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks are not available here")

            self.assertEqual(housekeeping.cleanup_old_runs(self.root, 1), [])
            self.assertTrue((target / "precious.txt").exists())

    def test_missing_folder_is_fine(self):
        self.assertEqual(
            housekeeping.cleanup_old_runs(self.root / "nope", 30), [])


if __name__ == "__main__":
    unittest.main()
