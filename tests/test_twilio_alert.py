import sqlite3
import tempfile
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


if __name__ == "__main__":
    unittest.main()
