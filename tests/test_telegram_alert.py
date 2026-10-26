import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app.alerts import telegram_alert as t

ENV = {"TELEGRAM_BOT_TOKEN": "123:SECRET", "TELEGRAM_CHAT_ID": "42"}


class TelegramTests(unittest.TestCase):
    def test_not_configured_sends_nothing(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "",
                                          "TELEGRAM_CHAT_ID": ""}):
            post = mock.Mock()

            self.assertEqual(t.send_alert("x", post=post), t.NOT_CONFIGURED)
            post.assert_not_called()

    def test_text_message(self):
        with mock.patch.dict(os.environ, ENV):
            post = mock.Mock(return_value={"ok": True})

            self.assertEqual(t.send_alert("hello", post=post), "sent")
            post.assert_called_once_with(
                "sendMessage", {"chat_id": "42", "text": "hello"})

    def test_photo_and_long_text(self):
        with mock.patch.dict(os.environ, ENV), \
                tempfile.TemporaryDirectory() as d:
            pic = Path(d) / "a.jpg"
            pic.write_bytes(b"x")
            post = mock.Mock(return_value={"ok": True})
            t.send_alert("y" * 5000, photo=pic, post=post)
            method, fields = post.call_args[0]

            self.assertEqual(method, "sendPhoto")
            self.assertLessEqual(len(fields["caption"]), 1000)
            self.assertEqual(post.call_args[1]["file"], ("photo", pic))

    def test_failures_never_leak_the_token(self):
        with mock.patch.dict(os.environ, ENV):
            err = urllib.error.HTTPError("https://x/bot123:SECRET/y", 401,
                                         "no", {}, None)
            status = t.send_alert("m", post=mock.Mock(side_effect=err))
            net = t.send_alert("m", post=mock.Mock(
                side_effect=urllib.error.URLError("bot123:SECRET down")))
            refused = t.send_alert("m", post=mock.Mock(return_value={"ok": False}))

        self.assertIn("401", status)
        self.assertNotIn("SECRET", status + net + refused)
        self.assertTrue(net.startswith("failed"))
        self.assertTrue(refused.startswith("failed"))

    def test_post_builds_multipart_and_json(self):
        with mock.patch.dict(os.environ, ENV), \
                tempfile.TemporaryDirectory() as d:
            seen = []

            class Resp:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return b'{"ok": true}'

            def opener(req, timeout):
                seen.append(req)
                return Resp()

            pic = Path(d) / "a.jpg"
            pic.write_bytes(b"JPEGDATA")
            t._post("sendMessage", {"chat_id": "42", "text": "hi"}, opener=opener)
            t._post("sendPhoto", {"chat_id": "42"}, file=("photo", pic),
                    opener=opener)

        self.assertIn("/bot123:SECRET/sendMessage", seen[0].full_url)
        self.assertIn(b'"text": "hi"', seen[0].data)
        self.assertIn("multipart/form-data", seen[1].headers["Content-type"])
        self.assertIn(b"JPEGDATA", seen[1].data)

    def test_notify_sync_and_thread(self):
        got = []
        t.notify("m", sync=True, sender=lambda m, p: "sent", on_done=got.append)
        thread = t.notify("m", sender=lambda m, p: "sent", on_done=got.append)
        thread.join()

        self.assertEqual(got, ["sent", "sent"])

    def test_cli_without_settings(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "",
                                          "TELEGRAM_CHAT_ID": ""}):
            self.assertEqual(t.main([]), 1)


if __name__ == "__main__":
    unittest.main()
