"""Twilio SMS / voice alerts for possible collisions.

Credentials are read from the environment (a ``.env`` file works). Nothing
is sent unless all four values are set, and callers decide whether an alert
is wanted at all: the upload page keeps alerts OFF by default so analysing
somebody's footage never texts an ambulance service by accident.
"""

import argparse
import os
import re
import sys
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:  # python-dotenv is optional here
    pass

from app.violation.violation_logger import set_alert_status

REQUIRED_SETTINGS = (
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "ALERT_TO_PHONE",
)

NOT_CONFIGURED = "skipped (Twilio not configured)"

REQUEST_TIMEOUT_SECONDS = 15

# International format: "+", a country code that does not start with 0, and
# 7 to 15 digits in all (for example +14155550123 or +919876543210).
E164 = re.compile(r"^\+[1-9]\d{6,14}$")

TEST_MESSAGE = (
    "Traffic Agent test message. No incident has happened; "
    "you can ignore this."
)

# Plain-language hints for the Twilio errors people hit most often. Only the
# numeric code is used, never Twilio's message text, because that text can
# contain phone numbers.
ERROR_HINTS = {
    20003: "check the Account SID and Auth Token",
    21211: "the number to alert is not valid",
    21212: "the Twilio number is not valid",
    21408: "this country is not enabled in Twilio Geo Permissions",
    21606: "the Twilio number cannot send messages",
    21608: "trial accounts can only reach verified numbers; verify "
           "ALERT_TO_PHONE in the Twilio console",
    21610: "the recipient has opted out of messages",
    21614: "the number to alert is not a mobile number",
}


def _setting(name):
    return os.getenv(name, "").strip()


def config_status():
    """Which settings are present. Never returns the secret values."""

    return {name: bool(_setting(name)) for name in REQUIRED_SETTINGS}


def is_configured():
    return all(config_status().values())


def config_problems():
    """Plain-language problems with the settings (empty when all is well).

    Missing settings are reported by ``config_status``; this also catches
    values that are present but certain to fail, such as a phone number
    without its country code.
    """

    problems = []

    if not is_configured():
        return problems

    if not _setting("TWILIO_ACCOUNT_SID").startswith("AC"):
        problems.append("TWILIO_ACCOUNT_SID should start with AC.")

    for name in ("TWILIO_PHONE_NUMBER", "ALERT_TO_PHONE"):
        if not E164.match(_setting(name)):
            problems.append(
                f"{name} must be in international format, "
                "like +14155550123."
            )

    if _setting("TWILIO_PHONE_NUMBER") == _setting("ALERT_TO_PHONE"):
        problems.append(
            "ALERT_TO_PHONE must be a different number from "
            "TWILIO_PHONE_NUMBER."
        )

    return problems


def is_ready():
    """Configured, and with no value that is certain to fail."""

    return is_configured() and not config_problems()


def voice_call_enabled():
    return os.getenv("ALERT_VOICE_CALL", "").strip().lower() in (
        "1", "true", "yes"
    )


def _default_client():
    from twilio.rest import Client

    sid, token = _setting("TWILIO_ACCOUNT_SID"), _setting("TWILIO_AUTH_TOKEN")

    # Twilio's default HTTP client has no timeout, so one stalled request
    # could hang the alert thread (and the program waiting for it) forever.
    try:
        from twilio.http.http_client import TwilioHttpClient

        return Client(
            sid, token,
            http_client=TwilioHttpClient(timeout=REQUEST_TIMEOUT_SECONDS),
        )
    except (ImportError, TypeError):
        return Client(sid, token)


def _describe(exc):
    """A short, safe description of a failure (no numbers, no secrets)."""

    if isinstance(exc, ImportError):
        return "the twilio package is not installed (pip install twilio)"

    code = getattr(exc, "code", None)

    if isinstance(code, int):
        hint = ERROR_HINTS.get(code)

        return f"Twilio error {code} ({hint})" if hint else f"Twilio error {code}"

    return type(exc).__name__


def send_alert(message, voice=None, client_factory=None):
    """Send an SMS (and optionally a voice call). Returns a status string.

    Statuses start with ``sent``, ``skipped`` or ``failed`` so the dashboard
    can group them. ``client_factory`` exists so tests can inject a fake.
    """

    if not is_configured():
        return NOT_CONFIGURED

    problems = config_problems()

    if problems:
        return f"failed: {problems[0]}"

    from_number = _setting("TWILIO_PHONE_NUMBER")
    to_number = _setting("ALERT_TO_PHONE")
    want_call = voice_call_enabled() if voice is None else voice

    try:
        client = (client_factory or _default_client)()
        client.messages.create(body=message, from_=from_number, to=to_number)
    except Exception as exc:
        return f"failed: {_describe(exc)}"

    if not want_call:
        return "sent"

    try:
        client.calls.create(
            twiml=f"<Response><Say>{escape(message)}</Say></Response>",
            from_=from_number,
            to=to_number,
        )
    except Exception as exc:
        return f"sent (sms only; call failed: {_describe(exc)})"

    return "sent (sms and call)"


def dispatch(event_id, message, sync=False, sender=send_alert, on_done=None):
    """Send the alert, then record the outcome on the collision event.

    ``on_done(status)`` is called with the final status once it is stored.

    Runs on a background thread by default so a slow Twilio request does not
    stall video processing. The thread is not a daemon, so an alert already
    in flight still finishes if the program ends right afterwards.
    """

    # The clock starts when the collision is handed to us, so the figure
    # covers any wait for the background thread as well as Twilio itself.
    detected_at = time.perf_counter()

    def work():
        try:
            status = sender(message)
        except Exception as exc:  # never lose the record of what happened
            status = f"failed: {_describe(exc)}"

        latency_ms = (time.perf_counter() - detected_at) * 1000
        set_alert_status(event_id, status, latency_ms=latency_ms)

        if on_done is not None:
            on_done(status)

    if sync:
        work()
        return None

    thread = threading.Thread(target=work)
    thread.start()

    return thread


def main(argv=None, client_factory=None):
    """Check the Twilio setup from a terminal: ``python -m app.alerts.twilio_alert``.

    With ``--send`` it sends one real test SMS to ALERT_TO_PHONE (and
    ``--call`` also places a test call). Exit status is 0 on success.
    """

    parser = argparse.ArgumentParser(
        prog="python -m app.alerts.twilio_alert",
        description="Check the Twilio settings and optionally send a test.",
    )
    parser.add_argument("--send", action="store_true",
                        help="send one real test SMS")
    parser.add_argument("--call", action="store_true",
                        help="with --send, also place a test voice call")
    args = parser.parse_args(argv)

    status = config_status()

    print("Twilio settings (values are never printed):")

    for name in REQUIRED_SETTINGS:
        print(f"  {name}: {'set' if status[name] else 'MISSING'}")

    print(f"  ALERT_VOICE_CALL: {'on' if voice_call_enabled() else 'off'}")

    if not is_configured():
        print("\nFill in the missing settings in .env (see .env.example).")
        return 1

    problems = config_problems()

    for problem in problems:
        print(f"\nProblem: {problem}")

    if problems:
        return 1

    if not args.send:
        print("\nSettings look valid. Run again with --send to send a "
              "test SMS.")
        return 0

    started = time.perf_counter()
    result = send_alert(
        TEST_MESSAGE,
        voice=args.call or None,
        client_factory=client_factory,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"\nResult: {result}  ({elapsed_ms:.0f} ms)")

    return 0 if result.startswith("sent") else 1


if __name__ == "__main__":
    sys.exit(main())
