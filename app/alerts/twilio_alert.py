"""Twilio SMS / voice alerts for possible collisions.

Credentials are read from the environment (a ``.env`` file works). Nothing
is sent unless all four values are set, and callers decide whether an alert
is wanted at all: the upload page keeps alerts OFF by default so analysing
somebody's footage never texts an ambulance service by accident.
"""

import os
import threading
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


def config_status():
    """Which settings are present. Never returns the secret values."""

    return {name: bool(os.getenv(name)) for name in REQUIRED_SETTINGS}


def is_configured():
    return all(config_status().values())


def voice_call_enabled():
    return os.getenv("ALERT_VOICE_CALL", "").strip().lower() in (
        "1", "true", "yes"
    )


def _default_client():
    from twilio.rest import Client

    return Client(
        os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    )


def send_alert(message, voice=None, client_factory=None):
    """Send an SMS (and optionally a voice call). Returns a status string.

    Statuses start with ``sent``, ``skipped`` or ``failed`` so the dashboard
    can group them. ``client_factory`` exists so tests can inject a fake.
    """

    if not is_configured():
        return NOT_CONFIGURED

    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    to_number = os.getenv("ALERT_TO_PHONE")
    want_call = voice_call_enabled() if voice is None else voice

    try:
        client = (client_factory or _default_client)()
        client.messages.create(body=message, from_=from_number, to=to_number)
    except Exception as exc:
        return f"failed: {type(exc).__name__}"

    if not want_call:
        return "sent"

    try:
        client.calls.create(
            twiml=f"<Response><Say>{escape(message)}</Say></Response>",
            from_=from_number,
            to=to_number,
        )
    except Exception as exc:
        return f"sent (sms only; call failed: {type(exc).__name__})"

    return "sent (sms and call)"


def dispatch(event_id, message, sync=False, sender=send_alert, on_done=None):
    """Send the alert, then record the outcome on the collision event.

    ``on_done(status)`` is called with the final status once it is stored.

    Runs on a background thread by default so a slow Twilio request does not
    stall video processing. The thread is not a daemon, so an alert already
    in flight still finishes if the program ends right afterwards.
    """

    def work():
        try:
            status = sender(message)
        except Exception as exc:  # never lose the record of what happened
            status = f"failed: {type(exc).__name__}"

        set_alert_status(event_id, status)

        if on_done is not None:
            on_done(status)

    if sync:
        work()
        return None

    thread = threading.Thread(target=work)
    thread.start()

    return thread
