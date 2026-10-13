import contextlib
import importlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import audit, ratelimit, users
from tests.fake_streamlit import FakeStreamlit, StopPage, install

FAST = 1000          # PBKDF2 rounds: fast for tests, real value in production


class TempDirTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.users_file = self.dir / "users.json"

        for target, name, value in (
            (users, "ITERATIONS", FAST),
            (users, "_DECOY", None),
            (audit, "DB_PATH", self.dir / "t.db"),
            (audit, "LOG_DIR", self.dir / "logs"),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        patcher = mock.patch.object(audit, "configure_logging")
        patcher.start()
        self.addCleanup(patcher.stop)

        ratelimit.USER_LIMITER.reset()
        ratelimit.ADDRESS_LIMITER.reset()
        self.addCleanup(ratelimit.USER_LIMITER.reset)
        self.addCleanup(ratelimit.ADDRESS_LIMITER.reset)


class PasswordHashTests(unittest.TestCase):

    def test_round_trip_and_wrong_password(self):
        stored = users.hash_password("correct horse", iterations=FAST)

        self.assertTrue(users.verify_password("correct horse", stored))
        self.assertFalse(users.verify_password("wrong horse", stored))
        self.assertNotIn("correct horse", stored)

    def test_each_hash_has_its_own_salt(self):
        self.assertNotEqual(users.hash_password("x" * 12, FAST),
                            users.hash_password("x" * 12, FAST))

    def test_unicode_passwords_work(self):
        stored = users.hash_password("pässwörd-密码!", iterations=FAST)

        self.assertTrue(users.verify_password("pässwörd-密码!", stored))

    def test_garbage_never_raises(self):
        for bad in ("", None, "plain", "a$b$c$d", "pbkdf2_sha256$x$y$z",
                    "md5$1$2$3", 5):
            self.assertFalse(users.verify_password("anything", bad))


class UsersFileTests(TempDirTestCase):

    def add(self, name="alice", password="long-enough-pw", role="viewer"):
        return users.add_user(name, password, role, self.users_file)

    def test_add_authenticate_and_roles(self):
        self.add("Alice", role="operator")

        self.assertEqual(
            users.authenticate("alice", "long-enough-pw", self.users_file),
            "operator")
        self.assertEqual(
            users.authenticate("ALICE ", "long-enough-pw", self.users_file),
            "operator")
        self.assertIsNone(
            users.authenticate("alice", "nope-nope-nope", self.users_file))
        self.assertIsNone(
            users.authenticate("bob", "long-enough-pw", self.users_file))

    def test_the_file_holds_hashes_not_passwords(self):
        self.add()
        text = self.users_file.read_text()

        self.assertNotIn("long-enough-pw", text)
        self.assertIn("pbkdf2_sha256", text)

    def test_the_file_is_private_on_unix(self):
        self.add()

        if os.name == "posix":
            self.assertEqual(self.users_file.stat().st_mode & 0o777, 0o600)

    def test_bad_requests_are_explained(self):
        for name, password, role, message in (
            ("a b", "long-enough-pw", "viewer", "username"),
            ("", "long-enough-pw", "viewer", "username"),
            ("alice", "short", "viewer", "at least"),
            ("alice", "long-enough-pw", "root", "Role"),
        ):
            with self.assertRaisesRegex(users.UserError, message):
                users.add_user(name, password, role, self.users_file)

    def test_duplicates_are_refused_unless_replacing(self):
        self.add()

        with self.assertRaisesRegex(users.UserError, "already exists"):
            self.add()

        users.add_user("alice", "another-long-pw", "admin", self.users_file,
                       replace=True)
        self.assertEqual(
            users.authenticate("alice", "another-long-pw", self.users_file),
            "admin")

    def test_change_password_and_remove(self):
        self.add("alice", role="admin")
        self.add("bob")
        users.set_password("bob", "brand-new-password", self.users_file)

        self.assertIsNone(
            users.authenticate("bob", "long-enough-pw", self.users_file))
        self.assertEqual(
            users.authenticate("bob", "brand-new-password", self.users_file),
            "viewer")

        users.remove_user("bob", self.users_file)
        self.assertEqual(list(users.load_users(self.users_file)), ["alice"])

        with self.assertRaisesRegex(users.UserError, "no user"):
            users.remove_user("bob", self.users_file)

    def test_the_last_admin_cannot_be_removed(self):
        self.add("alice", role="admin")

        with self.assertRaisesRegex(users.UserError, "only admin"):
            users.remove_user("alice", self.users_file)

    def test_missing_file_means_no_accounts(self):
        self.assertEqual(users.load_users(self.dir / "none.json"), {})

    def test_a_damaged_file_is_an_error_not_an_empty_list(self):
        for text in ("not json", "{}", '{"users": {"a": {"role": "god", '
                     '"password_hash": "x"}}}', '{"users": []}'):
            self.users_file.write_text(text)

            with self.assertRaisesRegex(users.UserError, "damaged"):
                users.load_users(self.users_file)

    def test_permissions(self):
        self.assertTrue(users.has_permission("viewer", "view"))
        self.assertFalse(users.has_permission("viewer", "operate"))
        self.assertTrue(users.has_permission("operator", "operate"))
        self.assertFalse(users.has_permission("operator", "admin"))
        self.assertTrue(users.has_permission("admin", "operate"))
        self.assertFalse(users.has_permission(None, "view"))
        self.assertFalse(users.has_permission("admin", "launch"))

    def test_unknown_users_cost_a_hash_too(self):
        with mock.patch.object(users, "verify_password",
                               wraps=users.verify_password) as verify:
            users.authenticate("nobody", "whatever-pw", self.users_file)

        self.assertEqual(verify.call_count, 1)

    def test_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        base = ["--file", str(self.users_file)]

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(users.main(base + [
                "add", "root", "--role", "admin", "--password",
                "long-enough-pw"]), 0)
            self.assertEqual(users.main(base + ["list"]), 0)
            self.assertEqual(users.main(base + [
                "add", "root", "--password", "long-enough-pw"]), 1)

        self.assertIn("Created root (admin)", out.getvalue())
        self.assertIn("root", out.getvalue())
        self.assertIn("already exists", err.getvalue())


class LimiterTests(unittest.TestCase):

    def setUp(self):
        self.now = [1000.0]
        self.limiter = ratelimit.LoginLimiter(
            max_failures=3, window=100, base_lockout=10, max_lockout=60,
            clock=lambda: self.now[0])

    def test_locks_after_the_limit_and_unlocks_later(self):
        for _ in range(2):
            self.assertEqual(self.limiter.record_failure("a"), 0)

        self.assertEqual(self.limiter.record_failure("a"), 10)
        self.assertEqual(self.limiter.seconds_locked("a"), 10)

        self.now[0] += 11
        self.assertEqual(self.limiter.seconds_locked("a"), 0)

    def test_each_repeat_lockout_is_longer_up_to_a_cap(self):
        durations = []

        for _ in range(5):
            for _ in range(3):
                duration = self.limiter.record_failure("a")

            durations.append(duration)
            self.now[0] += 1000

        self.assertEqual(durations, [10, 20, 40, 60, 60])

    def test_old_failures_expire(self):
        self.limiter.record_failure("a")
        self.limiter.record_failure("a")
        self.now[0] += 200

        self.assertEqual(self.limiter.record_failure("a"), 0)

    def test_success_clears_the_count(self):
        self.limiter.record_failure("a")
        self.limiter.record_failure("a")
        self.limiter.record_success("a")

        self.assertEqual(self.limiter.record_failure("a"), 0)

    def test_keys_are_independent(self):
        for _ in range(3):
            self.limiter.record_failure("a")

        self.assertEqual(self.limiter.seconds_locked("b"), 0)

    def test_memory_is_bounded(self):
        with mock.patch.object(ratelimit, "MAX_KEYS", 5):
            for number in range(20):
                self.limiter.record_failure(f"k{number}")

        self.assertLessEqual(len(self.limiter._state), 5)

    def test_helpers_use_both_user_and_address(self):
        ratelimit.USER_LIMITER.reset()
        ratelimit.ADDRESS_LIMITER.reset()

        for _ in range(5):
            ratelimit.record_failure("alice", "1.2.3.4")

        self.assertGreater(ratelimit.locked_seconds("alice", "9.9.9.9"), 0)
        self.assertEqual(ratelimit.locked_seconds("bob", "9.9.9.9"), 0)
        ratelimit.USER_LIMITER.reset()
        ratelimit.ADDRESS_LIMITER.reset()


class AuditTests(TempDirTestCase):

    def test_records_are_stored_newest_first(self):
        audit.record("login_ok", user="alice", role="admin", address="1.1.1.1")
        audit.record("live_start", user="alice", detail="Gate")
        rows = audit.recent()

        self.assertEqual([r["action"] for r in rows],
                         ["live_start", "login_ok"])
        self.assertEqual(rows[1]["username"], "alice")

    def test_line_breaks_cannot_forge_entries(self):
        audit.record("x", user="eve\nFAKE admin", detail="a\r\nb\x00c")
        row = audit.recent()[0]

        self.assertNotIn("\n", row["username"] + row["detail"])
        self.assertNotIn("\x00", row["detail"])

    def test_long_text_is_cut(self):
        audit.record("x", detail="y" * 5000)

        self.assertLessEqual(len(audit.recent()[0]["detail"]), 300)

    def test_a_broken_database_never_raises(self):
        with mock.patch.object(audit, "DB_PATH", self.dir):   # a folder
            self.assertFalse(audit.record("x"))

    def test_nothing_recorded_yet(self):
        self.assertEqual(audit.recent(), [])


class LoginPageTests(TempDirTestCase):

    def page(self, env, state=None, **kwargs):
        st = FakeStreamlit(**kwargs)
        st.session_state.update(state or {})
        self.addCleanup(install(st))
        auth = importlib.import_module("app.ui.auth")
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

        return st, auth

    def gate(self, auth):
        try:
            auth.require_login()
        except StopPage:
            return False

        return True

    # -- no sign-in -----------------------------------------------------

    def test_open_on_a_developer_machine_as_admin(self):
        st, auth = self.page({"USERS_FILE": str(self.users_file)})

        self.assertTrue(self.gate(auth))
        self.assertEqual(st.session_state["user"],
                         {"name": "local", "role": "admin"})

    def test_production_without_any_sign_in_refuses(self):
        st, auth = self.page({"APP_ENV": "production",
                              "USERS_FILE": str(self.users_file)})

        self.assertFalse(self.gate(auth))
        self.assertIn("DASHBOARD_PASSWORD is not set", st.text())
        self.assertNotIn("user", st.session_state)

    # -- shared password -----------------------------------------------

    def test_shared_password_signs_in_as_an_operator(self):
        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret",
             "USERS_FILE": str(self.users_file)},
            clicks={"Sign in"}, values={"login_password": "s3cret"})

        self.gate(auth)

        self.assertEqual(st.session_state["user"]["role"], "operator")
        self.assertTrue(st.session_state["authenticated"])

    def test_shared_password_role_can_be_lowered(self):
        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret", "DASHBOARD_PASSWORD_ROLE":
             "viewer", "USERS_FILE": str(self.users_file)},
            clicks={"Sign in"}, values={"login_password": "s3cret"})

        self.gate(auth)

        self.assertEqual(st.session_state["user"]["role"], "viewer")

    def test_a_bad_role_setting_stops_the_app(self):
        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret", "DASHBOARD_PASSWORD_ROLE":
             "emperor", "USERS_FILE": str(self.users_file)},
            clicks={"Sign in"}, values={"login_password": "s3cret"})

        self.assertFalse(self.gate(auth))
        self.assertIn("DASHBOARD_PASSWORD_ROLE", st.text())
        self.assertNotIn("user", st.session_state)

    def test_wrong_shared_password_is_refused(self):
        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret",
             "USERS_FILE": str(self.users_file)},
            clicks={"Sign in"}, values={"login_password": "nope"})

        self.assertFalse(self.gate(auth))
        self.assertNotIn("user", st.session_state)
        self.assertIn("not correct", st.text())
        self.assertEqual(st.session_state["login_failures"], 1)
        self.assertEqual(audit.recent()[0]["action"], "login_failed")

    def test_the_password_never_reaches_the_audit_log_or_screen(self):
        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret",
             "USERS_FILE": str(self.users_file)},
            clicks={"Sign in"}, values={"login_password": "guess-123"})

        self.gate(auth)

        self.assertNotIn("guess-123", json.dumps(audit.recent()))
        self.assertNotIn("guess-123", st.text())

    def test_guessing_the_shared_password_gets_locked_even_without_an_address(
            self):
        for _ in range(5):
            st, auth = self.page(
                {"DASHBOARD_PASSWORD": "s3cret",
                 "USERS_FILE": str(self.users_file)},
                clicks={"Sign in"}, values={"login_password": "guess"})
            self.gate(auth)

        st, auth = self.page(
            {"DASHBOARD_PASSWORD": "s3cret",
             "USERS_FILE": str(self.users_file)},
            clicks={"Sign in"}, values={"login_password": "s3cret"})

        self.assertFalse(self.gate(auth))
        self.assertIn("Too many failed attempts", st.text())

    # -- accounts -------------------------------------------------------

    def with_account(self, role="operator", **kwargs):
        users.add_user("alice", "long-enough-pw", role, self.users_file,
                       replace=True)
        env = {"USERS_FILE": str(self.users_file)}
        env.update(kwargs.pop("env", {}))

        return self.page(env, **kwargs)

    def test_accounts_switch_on_user_sign_in_automatically(self):
        st, auth = self.with_account()

        self.assertEqual(auth.mode(), "users")
        self.assertFalse(self.gate(auth))
        self.assertIn("Sign in with your account", st.text())
        self.assertEqual(len(st.called("form")), 1)

    def test_right_username_and_password_sign_in_with_the_role(self):
        st, auth = self.with_account(
            "admin", clicks={"Sign in"},
            values={"login_username": " Alice ",
                    "login_password": "long-enough-pw"})

        self.gate(auth)

        self.assertEqual(st.session_state["user"],
                         {"name": "alice", "role": "admin"})
        self.assertEqual(audit.recent()[0]["action"], "login_ok")

    def test_wrong_password_and_unknown_user_give_the_same_message(self):
        messages = []

        for name in ("alice", "nobody"):
            st, auth = self.with_account(
                clicks={"Sign in"},
                values={"login_username": name,
                        "login_password": "wrong-wrong-wrong"})
            self.gate(auth)
            messages.append([c for c in st.called("error")][0][1])

        self.assertEqual(messages[0], messages[1])

    def test_repeated_failures_lock_the_account_for_every_session(self):
        for _ in range(5):
            st, auth = self.with_account(
                clicks={"Sign in"},
                values={"login_username": "alice",
                        "login_password": "wrong-wrong-wrong"})
            self.gate(auth)

        # A brand-new session, now with the CORRECT password, is still held.
        st, auth = self.with_account(
            clicks={"Sign in"},
            values={"login_username": "alice",
                    "login_password": "long-enough-pw"})

        self.assertFalse(self.gate(auth))
        self.assertNotIn("user", st.session_state)
        self.assertIn("Too many failed attempts", st.text())
        self.assertEqual(audit.recent()[0]["action"], "login_blocked")

    def test_one_address_trying_many_users_is_slowed(self):
        headers = {"X-Forwarded-For": "6.6.6.6, 10.0.0.1"}

        for number in range(25):
            st, auth = self.with_account(
                clicks={"Sign in"}, headers=headers,
                values={"login_username": f"user{number}",
                        "login_password": "wrong-wrong-wrong"})
            self.gate(auth)

        st, auth = self.with_account(
            clicks={"Sign in"}, headers=headers,
            values={"login_username": "alice",
                    "login_password": "long-enough-pw"})

        self.assertFalse(self.gate(auth))
        self.assertIn("Too many failed attempts", st.text())

    def test_a_damaged_users_file_stops_the_app(self):
        self.users_file.write_text("garbage")
        st, auth = self.page({"USERS_FILE": str(self.users_file)})

        self.assertFalse(self.gate(auth))
        self.assertIn("damaged", st.text())
        self.assertNotIn("user", st.session_state)

    def test_signed_in_session_passes(self):
        st, auth = self.with_account(state={
            "authenticated": True,
            "user": {"name": "alice", "role": "viewer"}})

        self.assertTrue(self.gate(auth))
        self.assertEqual(st.called("form"), [])

    # -- proxy ----------------------------------------------------------

    PROXY = {"AUTH_MODE": "proxy", "AUTH_PROXY_ADMINS": "boss@x.org",
             "AUTH_PROXY_OPERATORS": "Op@X.org, other@x.org"}

    def proxy(self, email, **env):
        headers = {"X-Forwarded-Email": email} if email else {}

        return self.page({**self.PROXY, "USERS_FILE": str(self.users_file),
                          **env}, headers=headers)

    def test_proxy_roles_come_from_the_lists(self):
        for email, role in (("boss@x.org", "admin"), ("op@x.org", "operator"),
                            ("random@x.org", "viewer")):
            st, auth = self.proxy(email)

            self.assertTrue(self.gate(auth))
            self.assertEqual(st.session_state["user"],
                             {"name": email, "role": role})

    def test_proxy_default_role_is_configurable(self):
        st, auth = self.proxy("random@x.org", AUTH_PROXY_DEFAULT_ROLE="operator")
        self.gate(auth)

        self.assertEqual(st.session_state["user"]["role"], "operator")

    def test_without_the_header_nobody_gets_in(self):
        st, auth = self.proxy(None)

        self.assertFalse(self.gate(auth))
        self.assertIn("through the proxy", st.text())
        self.assertNotIn("user", st.session_state)

    def test_a_session_cannot_keep_a_role_the_proxy_no_longer_grants(self):
        st, auth = self.proxy("random@x.org", **{})
        st.session_state["user"] = {"name": "random@x.org", "role": "admin"}

        self.gate(auth)

        self.assertEqual(st.session_state["user"]["role"], "viewer")

    def test_proxy_mode_has_no_sign_out_button_of_its_own(self):
        st, auth = self.proxy("boss@x.org")
        self.gate(auth)
        auth.logout_button()

        self.assertEqual(st.called("button"), [])
        self.assertIn("boss@x.org", st.text())

    # -- permissions and sign-out ----------------------------------------

    def test_can_and_require(self):
        for role, operate, admin in (("viewer", False, False),
                                     ("operator", True, False),
                                     ("admin", True, True)):
            st, auth = self.page({}, state={"user": {"name": "u",
                                                     "role": role}})
            self.assertTrue(auth.can("view"))
            self.assertEqual(auth.can("operate"), operate)
            self.assertEqual(auth.can("admin"), admin)

        st, auth = self.page({}, state={"user": {"name": "u",
                                                 "role": "viewer"}})
        self.assertFalse(auth.require("operate", "start a camera"))
        self.assertIn("cannot start a camera", st.text())

    def test_nobody_signed_in_can_do_nothing(self):
        st, auth = self.page({})

        self.assertFalse(auth.can("view"))

    def test_sign_out_clears_the_user_and_is_logged(self):
        st, auth = self.with_account(
            state={"authenticated": True,
                   "user": {"name": "alice", "role": "operator"}},
            clicks={"logout"})

        auth.logout_button()

        self.assertFalse(st.session_state["authenticated"])
        self.assertNotIn("user", st.session_state)
        self.assertEqual(audit.recent()[0]["action"], "logout")

    def test_no_sign_out_button_when_open(self):
        st, auth = self.page({"USERS_FILE": str(self.users_file)})
        auth.logout_button()

        self.assertEqual(st.called("button"), [])

    def test_bad_auth_mode_is_reported(self):
        st, auth = self.page({"AUTH_MODE": "magic",
                              "USERS_FILE": str(self.users_file)})

        self.assertFalse(self.gate(auth))
        self.assertIn("AUTH_MODE", st.text())


if __name__ == "__main__":
    unittest.main()
