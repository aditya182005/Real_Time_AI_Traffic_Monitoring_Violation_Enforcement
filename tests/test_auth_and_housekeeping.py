import importlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app import housekeeping
from tests.fake_streamlit import FakeStreamlit, StopPage, install


class LoginTests(unittest.TestCase):

    def page(self, env, state=None, **kwargs):
        st = FakeStreamlit(**kwargs)
        st.session_state.update(state or {})
        self.addCleanup(install(st))
        auth = importlib.import_module("app.ui.auth")
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

        return st, auth

    def run_gate(self, auth):
        """Returns True if the page may continue, False if it was stopped."""

        try:
            auth.require_login()
        except StopPage:
            return False

        return True

    def test_open_when_no_password_is_set(self):
        st, auth = self.page({})

        self.assertTrue(self.run_gate(auth))
        self.assertEqual(st.called("form"), [])

    def test_production_without_a_password_refuses_to_run(self):
        st, auth = self.page({"APP_ENV": "production"})

        self.assertFalse(self.run_gate(auth))
        self.assertIn("DASHBOARD_PASSWORD is not set", st.text())

    def test_production_with_a_password_asks_for_it(self):
        st, auth = self.page({"APP_ENV": "production",
                              "DASHBOARD_PASSWORD": "s3cret"})

        self.assertFalse(self.run_gate(auth))
        self.assertEqual(len(st.called("form")), 1)
        self.assertNotIn("s3cret", st.text())

    def test_correct_password_signs_in(self):
        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret"},
            clicks={"Sign in"}, values={"login_password": "s3cret"})

        self.run_gate(auth)

        self.assertTrue(st.session_state["authenticated"])
        self.assertEqual(len(st.called("rerun")), 1)

    def test_wrong_password_is_refused_and_counted(self):
        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret"},
            clicks={"Sign in"}, values={"login_password": "nope"})

        self.assertFalse(self.run_gate(auth))
        self.assertFalse(st.session_state.get("authenticated"))
        self.assertEqual(st.session_state["login_failures"], 1)
        self.assertIn("not correct", st.text())

    def test_already_signed_in_session_passes(self):
        st, auth = self.page({"DASHBOARD_PASSWORD": "s3cret"},
                             state={"authenticated": True})

        self.assertTrue(self.run_gate(auth))
        self.assertEqual(st.called("form"), [])

    def test_repeated_failures_are_slowed_down(self):
        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret"},
            state={"login_failures": 5},
            clicks={"Sign in"}, values={"login_password": "nope"})

        with mock.patch.object(auth.time, "sleep") as sleep:
            self.run_gate(auth)

        sleep.assert_called_once()
        self.assertGreater(sleep.call_args[0][0], 0)

    def test_first_few_failures_are_not_delayed(self):
        st, auth = self.page({"DASHBOARD_PASSWORD": "x"})

        self.assertEqual([auth._delay_for(n) for n in (0, 1, 2)], [0, 0, 0])
        self.assertGreater(auth._delay_for(3), 0)
        self.assertEqual(auth._delay_for(50), auth.MAX_DELAY_SECONDS)

    def test_comparison_handles_unicode_and_is_exact(self):
        st, auth = self.page({})

        self.assertTrue(auth.password_matches("pässword", "pässword"))
        self.assertFalse(auth.password_matches("password", "pässword"))
        self.assertFalse(auth.password_matches("", "x"))

    def test_sign_out_only_appears_when_a_password_is_set(self):
        st, auth = self.page({})
        auth.logout_button()
        self.assertEqual(st.called("button"), [])

        st, auth = self.page({"DASHBOARD_PASSWORD": "x"},
                             state={"authenticated": True},
                             clicks={"logout"})
        auth.logout_button()
        self.assertFalse(st.session_state["authenticated"])


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
                           state={"authenticated": True})

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
