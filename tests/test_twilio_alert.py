import contextlib
import io
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from app.alerts import twilio_alert
from app.violation import violation_logger as vl

ENV = {
    "TWILIO_ACCOUNT_SID": "AC123",
    "TWILIO_AUTH_TOKEN": "secret",
    "TWILIO_PHONE_NUMBER": "+15550001",
    "ALERT_TO_PHONE": "+15550002",
}


class FakeClient:
    def __init__(self, fail_sms=False, fail_call=False):
        self.sent, self.called = [], []
        self.fail_sms, self.fail_call = fail_sms, fail_call
        client = self

        class Messages:
            def create(self, **kwargs):
                if client.fail_sms:
                    raise RuntimeError("boom")
                client.sent.append(kwargs)

        class Calls:
            def create(self, **kwargs):
                if client.fail_call:
                    raise RuntimeError("boom")
                client.called.append(kwargs)

        self.messages, self.calls = Messages(), Calls()


class SendAlertTests(unittest.TestCase):

    def run_alert(self, env=ENV, **kwargs):
        client = FakeClient(
            kwargs.pop("fail_sms", False), kwargs.pop("fail_call", False)
        )

        with mock.patch.dict("os.environ", env, clear=True):
            status = twilio_alert.send_alert(
                kwargs.pop("message", "hello"),
                client_factory=lambda: client, **kwargs
            )

        return status, client

    def test_skipped_when_not_configured(self):
        status, client = self.run_alert(env={})

        self.assertEqual(status, twilio_alert.NOT_CONFIGURED)
        self.assertEqual(client.sent, [])

    def test_one_missing_setting_is_not_configured(self):
        env = {k: v for k, v in ENV.items() if k != "ALERT_TO_PHONE"}

        self.assertTrue(self.run_alert(env=env)[0].startswith("skipped"))

    def test_sms_is_sent_with_numbers_from_the_environment(self):
        status, client = self.run_alert(message="crash")

        self.assertEqual(status, "sent")
        self.assertEqual(client.sent, [{
            "body": "crash", "from_": "+15550001", "to": "+15550002",
        }])
        self.assertEqual(client.called, [])

    def test_voice_call_is_optional(self):
        status, client = self.run_alert(voice=True, message="a < b & c")

        self.assertEqual(status, "sent (sms and call)")
        # The spoken message is XML-escaped inside the TwiML.
        self.assertIn("a &lt; b &amp; c", client.called[0]["twiml"])

    def test_voice_can_be_enabled_from_the_environment(self):
        status, _ = self.run_alert(env={**ENV, "ALERT_VOICE_CALL": "1"})

        self.assertEqual(status, "sent (sms and call)")

    def test_failures_are_reported_not_raised(self):
        status, _ = self.run_alert(fail_sms=True)
        self.assertEqual(status, "failed: RuntimeError")

        status, _ = self.run_alert(voice=True, fail_call=True)
        self.assertTrue(status.startswith("sent (sms only"))

    def test_config_status_never_contains_secret_values(self):
        with mock.patch.dict("os.environ", ENV, clear=True):
            status = twilio_alert.config_status()

        self.assertEqual(set(status.values()), {True})
        self.assertNotIn("secret", repr(status))


class DispatchTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "t.db"
        patcher = mock.patch.object(vl, "DB_PATH", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.event_id = vl.log_collision_event(1, 2, "e.jpg", camera_id="C1")

    def status(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(
                "SELECT alert_status FROM collision_events WHERE id=?",
                (self.event_id,),
            ).fetchone()[0]

    def test_outcome_is_stored_on_the_collision_record(self):
        self.assertEqual(self.status(), "pending")

        seen = []
        twilio_alert.dispatch(
            self.event_id, "m", sync=True,
            sender=lambda message: "sent", on_done=seen.append,
        )

        self.assertEqual(self.status(), "sent")
        self.assertEqual(seen, ["sent"])

    def test_background_thread_stores_the_outcome(self):
        thread = twilio_alert.dispatch(
            self.event_id, "m", sender=lambda message: "sent"
        )
        thread.join(5)

        self.assertEqual(self.status(), "sent")

    def test_sender_crash_is_recorded_as_failed(self):
        def broken(message):
            raise ValueError("x")

        twilio_alert.dispatch(self.event_id, "m", sync=True, sender=broken)

        self.assertEqual(self.status(), "failed: ValueError")


class TwilioError(Exception):
    """Looks like twilio.base.exceptions.TwilioRestException."""

    def __init__(self, code, msg="The number +15550002 is unverified"):
        super().__init__(msg)
        self.code, self.msg = code, msg


class ValidationTests(unittest.TestCase):

    def problems(self, **overrides):
        with mock.patch.dict("os.environ", {**ENV, **overrides}, clear=True):
            return twilio_alert.config_problems()

    def test_valid_settings_have_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_numbers_must_have_a_country_code(self):
        problems = self.problems(ALERT_TO_PHONE="9876543210")

        self.assertEqual(len(problems), 1)
        self.assertIn("ALERT_TO_PHONE", problems[0])
        self.assertIn("international format", problems[0])

    def test_account_sid_must_start_with_ac(self):
        self.assertIn("TWILIO_ACCOUNT_SID should start with AC",
                      self.problems(TWILIO_ACCOUNT_SID="xyz")[0])

    def test_cannot_alert_the_twilio_number_itself(self):
        problems = self.problems(ALERT_TO_PHONE="+15550001")

        self.assertIn("different number", problems[0])

    def test_values_with_stray_spaces_are_accepted(self):
        self.assertEqual(self.problems(ALERT_TO_PHONE=" +15550002 "), [])

    def test_missing_settings_are_not_reported_as_problems(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(twilio_alert.config_problems(), [])
            self.assertFalse(twilio_alert.is_ready())

    def test_invalid_numbers_are_refused_without_calling_twilio(self):
        client = FakeClient()

        with mock.patch.dict("os.environ", {**ENV, "ALERT_TO_PHONE": "123"},
                             clear=True):
            status = twilio_alert.send_alert(
                "hi", client_factory=lambda: client)

        self.assertTrue(status.startswith("failed: ALERT_TO_PHONE"))
        self.assertEqual(client.sent, [])


class ErrorReportingTests(unittest.TestCase):

    def status_for(self, error, **kwargs):
        class Client:
            class messages:
                @staticmethod
                def create(**kw):
                    raise error

            class calls:
                @staticmethod
                def create(**kw):
                    raise error

        with mock.patch.dict("os.environ", ENV, clear=True):
            return twilio_alert.send_alert(
                "hi", client_factory=Client, **kwargs)

    def test_known_twilio_errors_get_a_plain_hint(self):
        status = self.status_for(TwilioError(21608))

        self.assertIn("Twilio error 21608", status)
        self.assertIn("verify ALERT_TO_PHONE", status)

    def test_unknown_twilio_errors_keep_the_code(self):
        self.assertEqual(self.status_for(TwilioError(99999)),
                         "failed: Twilio error 99999")

    def test_twilios_message_text_is_never_stored(self):
        # It can contain phone numbers, which the dashboard hides.
        status = self.status_for(TwilioError(21608))

        self.assertNotIn("+1555", status)
        self.assertNotIn("unverified", status)

    def test_missing_package_says_how_to_fix_it(self):
        status = self.status_for(ImportError("No module named twilio"))

        self.assertIn("pip install twilio", status)

    def test_call_failure_is_described_too(self):
        class Client:
            class messages:
                @staticmethod
                def create(**kw):
                    return None

            class calls:
                @staticmethod
                def create(**kw):
                    raise TwilioError(21211)

        with mock.patch.dict("os.environ", ENV, clear=True):
            status = twilio_alert.send_alert(
                "hi", voice=True, client_factory=Client)

        self.assertTrue(status.startswith("sent (sms only; call failed"))
        self.assertIn("21211", status)


class DefaultClientTests(unittest.TestCase):
    """The real SDK is not installed here, so use stand-in modules."""

    def install(self, http_client_class):
        created = {}

        class Client:
            def __init__(self, sid, token, **kwargs):
                created.update(sid=sid, token=token, kwargs=kwargs)

        modules = {
            "twilio": types.ModuleType("twilio"),
            "twilio.rest": types.ModuleType("twilio.rest"),
            "twilio.http": types.ModuleType("twilio.http"),
            "twilio.http.http_client": types.ModuleType(
                "twilio.http.http_client"),
        }
        modules["twilio.rest"].Client = Client
        modules["twilio.http.http_client"].TwilioHttpClient = http_client_class
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)

        return created

    def test_requests_have_a_timeout(self):
        class Http:
            def __init__(self, timeout=None):
                self.timeout = timeout

        created = self.install(Http)

        with mock.patch.dict("os.environ", ENV, clear=True):
            twilio_alert._default_client()

        self.assertEqual((created["sid"], created["token"]),
                         ("AC123", "secret"))
        self.assertEqual(created["kwargs"]["http_client"].timeout,
                         twilio_alert.REQUEST_TIMEOUT_SECONDS)

    def test_older_sdk_without_timeout_support_still_works(self):
        class OldHttp:
            def __init__(self):
                pass

        created = self.install(OldHttp)

        with mock.patch.dict("os.environ", ENV, clear=True):
            twilio_alert._default_client()

        self.assertEqual(created["kwargs"], {})


class SelfTestCommandTests(unittest.TestCase):

    def run_main(self, env, *argv, client=None):
        out = io.StringIO()

        with mock.patch.dict("os.environ", env, clear=True), \
                contextlib.redirect_stdout(out):
            code = twilio_alert.main(
                list(argv), client_factory=(lambda: client) if client else None)

        return code, out.getvalue()

    def test_reports_missing_settings_without_values(self):
        code, text = self.run_main({"TWILIO_ACCOUNT_SID": "AC123"})

        self.assertEqual(code, 1)
        self.assertIn("TWILIO_ACCOUNT_SID: set", text)
        self.assertIn("TWILIO_AUTH_TOKEN: MISSING", text)
        self.assertNotIn("AC123", text)

    def test_valid_settings_pass_without_sending(self):
        client = FakeClient()
        code, text = self.run_main(ENV, client=client)

        self.assertEqual(code, 0)
        self.assertEqual(client.sent, [])
        self.assertIn("--send", text)

    def test_send_flag_sends_one_test_message(self):
        client = FakeClient()
        code, text = self.run_main(ENV, "--send", client=client)

        self.assertEqual(code, 0)
        self.assertEqual(len(client.sent), 1)
        self.assertEqual(client.sent[0]["body"], twilio_alert.TEST_MESSAGE)
        self.assertIn("Result: sent", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("+1555000", text)

    def test_call_flag_also_places_a_call(self):
        client = FakeClient()
        code, _ = self.run_main(ENV, "--send", "--call", client=client)

        self.assertEqual(code, 0)
        self.assertEqual(len(client.called), 1)

    def test_failed_send_exits_non_zero(self):
        client = FakeClient(fail_sms=True)
        code, text = self.run_main(ENV, "--send", client=client)

        self.assertEqual(code, 1)
        self.assertIn("Result: failed", text)

    def test_bad_number_is_explained(self):
        code, text = self.run_main({**ENV, "ALERT_TO_PHONE": "12345"})

        self.assertEqual(code, 1)
        self.assertIn("international format", text)


if __name__ == "__main__":
    unittest.main()
