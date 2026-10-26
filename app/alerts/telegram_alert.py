"""Telegram alerts, an optional second channel next to Twilio.

Set ``TELEGRAM_BOT_TOKEN`` (from @BotFather) and ``TELEGRAM_CHAT_ID`` in
``.env``. Nothing is sent unless both are set and the run has alerts turned
on. Uses only the standard library, so no extra package is needed.

    python -m app.alerts.telegram_alert --send     # one test message
"""

import argparse
import json
import mimetypes
import os
import sys
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

REQUIRED_SETTINGS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
NOT_CONFIGURED = "skipped (Telegram not configured)"
TIMEOUT_SECONDS = 15
API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 3900          # Telegram's limit is 4096 characters


def _setting(name):
    return os.getenv(name, "").strip()


def is_configured():
    return all(_setting(name) for name in REQUIRED_SETTINGS)


def _post(method, fields, file=None, opener=urllib.request.urlopen):
    """POST to the Bot API. ``file`` is (field, path). Returns parsed JSON."""

    url = API.format(token=_setting("TELEGRAM_BOT_TOKEN"), method=method)

    if file is None:
        body = json.dumps(fields).encode()
        headers = {"Content-Type": "application/json"}
    else:
        boundary = uuid.uuid4().hex
        parts = []

        for key, value in fields.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; '
                f'name="{key}"\r\n\r\n{value}\r\n'.encode())

        field, path = file
        path = Path(path)
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
            f'filename="{path.name}"\r\nContent-Type: {kind}\r\n\r\n'.encode()
            + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}

    request = urllib.request.Request(url, data=body, headers=headers)

    with opener(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode() or "{}")


def send_alert(message, photo=None, post=_post):
    """Send the message (with a picture when ``photo`` is a readable file).

    Returns a short status text; never raises and never includes the token.
    """

    if not is_configured():
        return NOT_CONFIGURED

    chat = _setting("TELEGRAM_CHAT_ID")
    text = str(message)[:MAX_TEXT]

    try:
        if photo and Path(photo).is_file():
            result = post("sendPhoto", {"chat_id": chat, "caption": text[:1000]},
                          file=("photo", photo))
        else:
            result = post("sendMessage", {"chat_id": chat, "text": text})
    except urllib.error.HTTPError as exc:
        return f"failed: Telegram answered {exc.code}" + (
            " (check the bot token and chat id)" if exc.code in (400, 401, 404)
            else "")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return f"failed: {type(exc).__name__}"

    return "sent" if result.get("ok") else "failed: Telegram refused the message"


def notify(message, photo=None, sync=False, sender=send_alert, on_done=None):
    """Send in the background (a slow network must not stall the video)."""

    def work():
        status = sender(message, photo)

        if on_done:
            on_done(status)

    if sync:
        work()
        return None

    thread = threading.Thread(target=work)
    thread.start()

    return thread


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.alerts.telegram_alert")
    parser.add_argument("--send", action="store_true",
                        help="send one test message")
    args = parser.parse_args(argv)

    for name in REQUIRED_SETTINGS:
        print(f"{name}: {'set' if _setting(name) else 'MISSING'}")

    if not is_configured():
        print("Set both in .env (token from @BotFather; chat id from "
              "https://api.telegram.org/bot<token>/getUpdates after messaging "
              "the bot).")
        return 1

    if not args.send:
        print("Add --send to send a test message.")
        return 0

    status = send_alert("Traffic Agent test message. No incident has "
                        "happened; you can ignore this.")
    print(status)

    return 0 if status == "sent" else 1


if __name__ == "__main__":
    sys.exit(main())
