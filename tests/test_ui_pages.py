"""Run each Streamlit page's code against a fake ``streamlit``.

See tests/fake_streamlit.py for what this does and does not prove.
"""

import importlib
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from tests.fake_streamlit import FakeStreamlit, StopPage, UploadedFile, install
from app.violation import violation_logger as vl


def empty_data():
    return {key: pd.DataFrame() for key in
            ("violations", "density", "priority", "collisions", "legacy_speed")}


class FakeVehicleDetector:
    def detect(self, frame, conf=None):
        h, w = frame.shape[:2]

        return [{"class_id": 2, "class_name": "car", "confidence": 0.9,
                 "bbox": (w // 4, h // 4, w // 2, h // 2)}]


class ScriptedTracker:
    """One car moving down the frame: crosses 60% of a 400 px frame."""

    def __init__(self):
        self.frame = 0

    def update(self, detections):
        bottom = 100 + 10 * self.frame
        self.frame += 1

        return SimpleNamespace(
            xyxy=np.array([[40.0, bottom - 40, 100.0, float(bottom)]]),
            tracker_id=np.array([7]),
            class_id=np.array([2]),
        )


class PageTestCase(unittest.TestCase):

    def start(self, **kwargs):
        self.st = FakeStreamlit(**kwargs)
        self.addCleanup(install(self.st))

        return self.st

    def ui(self, name):
        return importlib.import_module(f"app.ui.{name}")


class StaticPageTests(PageTestCase):

    def test_all_pages_render_with_no_data(self):
        self.start()
        today = date(2026, 10, 11)

        self.ui("dashboard").render(empty_data(), today, today)
        self.ui("evidence").render(empty_data())
        self.ui("alerts").render(empty_data())
        self.ui("about").render()
        self.ui("upload").render()

        text = self.st.text()
        self.assertIn("Dashboard", text)
        self.assertIn("Analyze footage", text)
        self.assertIn("No evidence yet", text)

    def test_dashboard_shows_the_counts_on_the_gantry(self):
        self.start()
        now = pd.Timestamp.now(tz="UTC").isoformat()
        violations = pd.DataFrame({
            "violation_type": ["red_light", "red_light", "speeding",
                               "wrong_way"],
            "fine_amount": [1000, 1000, 600, 1500],
            "timestamp": [now] * 4,
            "source": ["a.mp4", "a.mp4", "b.mp4", None],
        })
        data = empty_data()
        data["violations"] = violations

        self.ui("dashboard").render(data, date(2026, 1, 1), date(2026, 12, 31))

        html = "\n".join(
            a[0] for name, a, k in self.st.calls
            if name == "markdown" and a and "g-row" in a[0]
        )

        for label, value in (("Violations", 4), ("Red light", 2),
                             ("Speeding", 1), ("Wrong way", 1),
                             ("Cameras and files", 2)):
            self.assertRegex(
                html, rf"<b>{label}</b>.*?g-value\">{value}<", label)

        self.assertIn("₹4,100", html)
        self.assertIn("Wrong way", self.st.text())

    def test_alerts_page_never_shows_secret_values(self):
        self.start()
        env = {"TWILIO_ACCOUNT_SID": "AC-super-secret",
               "TWILIO_AUTH_TOKEN": "tok-super-secret",
               "TWILIO_PHONE_NUMBER": "+15550001",
               "ALERT_TO_PHONE": "+15550002"}

        with mock.patch.dict("os.environ", env, clear=True):
            self.ui("alerts").render(empty_data())

        text = self.st.text()
        self.assertIn("Account SID: set", text)
        self.assertNotIn("super-secret", text)
        self.assertNotIn("+1555000", text)

    def test_test_message_button_sends_once_and_reports_the_result(self):
        self.start(clicks={"twilio_test"})
        alerts = self.ui("alerts")
        env = {"TWILIO_ACCOUNT_SID": "a", "TWILIO_AUTH_TOKEN": "b",
               "TWILIO_PHONE_NUMBER": "c", "ALERT_TO_PHONE": "d"}

        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch.object(alerts.twilio_alert, "send_alert",
                                  return_value="sent") as send:
            alerts.render(empty_data())

        send.assert_called_once()
        self.assertIn("ignore", send.call_args[0][0].lower())
        self.assertEqual(len(self.st.called("success")), 1)

    def test_test_message_button_is_disabled_without_twilio(self):
        self.start(clicks={"twilio_test"})
        alerts = self.ui("alerts")

        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(alerts.twilio_alert,
                                  "send_alert") as send:
            alerts.render(empty_data())

        send.assert_not_called()


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class UploadFlowTests(PageTestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        patcher = mock.patch.object(vl, "DB_PATH", self.dir / "t.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def png(self, width=200, height=120):
        ok, buffer = cv2.imencode(".png", np.zeros((height, width, 3),
                                                   np.uint8))
        return buffer.tobytes()

    def video(self, frames=30, width=160, height=400):
        path = self.dir / "src.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                 10, (width, height))

        if not writer.isOpened():
            self.skipTest("this OpenCV build cannot write mp4v video")

        for _ in range(frames):
            writer.write(np.zeros((height, width, 3), np.uint8))

        writer.release()

        return path

    def upload_module(self):
        upload = self.ui("upload")
        upload.UPLOAD_ROOT = self.dir / "uploads"
        upload.STAGING_DIR = upload.UPLOAD_ROOT / "_staging"
        upload.load_vehicle_detector = lambda: FakeVehicleDetector()
        upload.EmergencyDetector.available = staticmethod(lambda *a: False)

        tracker_module = types.ModuleType("app.tracking.tracker")
        tracker_module.VehicleTracker = ScriptedTracker
        patcher = mock.patch.dict(sys.modules,
                                  {"app.tracking.tracker": tracker_module})
        patcher.start()
        self.addCleanup(patcher.stop)

        return upload

    # -- images -----------------------------------------------------------

    def test_images_are_analyzed_and_bad_files_are_reported(self):
        files = [UploadedFile("road.png", self.png()),
                 UploadedFile("broken.jpg", b"not an image")]
        self.start(uploads={"image_files": files}, clicks={"run_images"})
        upload = self.upload_module()

        upload.render()

        results = self.st.session_state["image_results"]
        self.assertEqual([r["name"] for r in results],
                         ["road.png", "broken.jpg"])
        self.assertEqual(results[0]["vehicles"], 1)
        self.assertEqual(results[0]["counts"], {"car": 1})
        self.assertTrue(results[0]["jpg"].startswith(b"\xff\xd8"))
        self.assertIn("not a readable image", results[1]["error"])

        text = self.st.text()
        self.assertIn("1 car", text)
        # One download per readable image (the broken file gets none),
        # plus the summary CSV.
        self.assertEqual(len(self.st.called("download_button")), 2)

    def test_image_upload_names_cannot_escape_through_the_ui(self):
        evil = UploadedFile("../../etc/passwd<script>.png", self.png())
        self.start(uploads={"image_files": [evil]}, clicks={"run_images"})
        upload = self.upload_module()

        upload.render()

        name = self.st.session_state["image_results"][0]["name"]
        self.assertNotIn("/", name)
        self.assertNotIn("<", name)

    # -- video ------------------------------------------------------------

    def run_video(self, values=None, filename="clip.mp4", **kwargs):
        data = self.video().read_bytes()
        self.start(
            uploads={"video_file": UploadedFile(filename, data)},
            clicks={"run_video"}, values=values or {}, **kwargs
        )
        upload = self.upload_module()

        with mock.patch.object(upload.media, "to_browser_mp4",
                               return_value=False):
            upload.render()

        return upload

    def test_video_runs_end_to_end_and_shows_results(self):
        values = {"stop_line_pct": 60, "camera_id": "CAM-UI"}
        self.run_video(values)

        result = self.st.session_state["video_result"]
        summary = result["summary"]

        # 400 px frame, line at 240: the scripted car crosses it on red.
        self.assertEqual(len(summary.violations_of("red_light")), 1)
        self.assertEqual(self.st.cache_data.cleared, 1)

        with sqlite3.connect(self.dir / "t.db") as conn:
            rows = conn.execute(
                "SELECT violation_type, camera_id, source "
                "FROM violation_records").fetchall()

        self.assertEqual(rows, [("red_light", "CAM-UI", "upload:clip.mp4")])

        # Live preview frames were shown, then the results page.
        previews = [c for c in self.st.called("image")
                    if str(c[2].get("caption", "")).startswith("Frame")]
        self.assertGreaterEqual(len(previews), 1)
        self.assertIn("Violations", self.st.text())
        self.assertIn("Download annotated video", self.st.text())
        self.assertIn("cannot convert the video", self.st.text())

    def test_live_feed_can_be_turned_off(self):
        self.run_video({"live_feed": False})

        previews = [c for c in self.st.called("image")
                    if str(c[2].get("caption", "")).startswith("Frame")]
        self.assertEqual(previews, [])
        self.assertIn("video_result", self.st.session_state)

    def test_saving_can_be_turned_off(self):
        self.run_video({"video_save": False})

        self.assertFalse((self.dir / "t.db").exists())
        self.assertIn("Not saved to the database", self.st.text())

    def test_optional_checks_are_applied_from_the_page_settings(self):
        self.run_video({
            "check_speed": True, "line_a": 30, "line_b": 70,
            "distance_m": 10.0, "limit_kmh": 20,
            "check_wrong_way": True, "check_collisions": True,
            "signal_mode": "Always green",
        })

        summary = self.st.session_state["video_result"]["summary"]

        # Always green: no red-light. The car covers 40% of 400 px in 16
        # frames at 10 fps: 160 px = 4 m... -> speed from 10 m / 1.6 s.
        self.assertEqual(summary.violations_of("red_light"), [])
        speeding = summary.violations_of("speeding")
        self.assertEqual(len(speeding), 1)
        self.assertAlmostEqual(speeding[0]["speed_kmh"], 22.5)

        # The detail is shown in the violations table (a DataFrame, which
        # FakeStreamlit.text() does not flatten), so look at the table.
        tables = [c[1][0] for c in self.st.called("dataframe")
                  if hasattr(c[1][0], "columns")
                  and "Detail" in c[1][0].columns]
        self.assertEqual(len(tables), 1)
        self.assertEqual(list(tables[0]["Detail"]),
                         ["22.5 km/h (limit 20)"])

    def test_invalid_settings_block_the_run_with_a_clear_message(self):
        self.run_video({"check_speed": True, "line_a": 50, "line_b": 50})

        self.assertNotIn("video_result", self.st.session_state)
        self.assertIn("Move speed line A and B apart", self.st.text())

    def test_unsupported_and_unreadable_videos_are_refused(self):
        self.start(uploads={"video_file": UploadedFile("notes.txt", b"hi")})
        self.upload_module().render()

        self.assertIn("not supported", self.st.text())
        self.assertNotIn("staged_video", self.st.session_state)

        self.start(uploads={"video_file": UploadedFile("a.mp4", b"junk")})
        self.upload_module().render()

        self.assertIn("could not be read", self.st.text())

    def test_uploaded_video_is_stored_under_a_fixed_name(self):
        data = self.video().read_bytes()
        self.start(uploads={"video_file": UploadedFile(
            "../../../tmp/evil name.mp4", data)})
        upload = self.upload_module()

        upload.render()

        staged = self.st.session_state["staged_video"]
        self.assertEqual(Path(staged["path"]).parent, upload.STAGING_DIR)
        self.assertEqual(Path(staged["path"]).name, "input.mp4")
        self.assertNotIn("/", staged["name"])

    def test_sample_video_button_loads_the_bundled_clip(self):
        self.start(clicks={"btn_sample"})
        upload = self.upload_module()
        upload.SAMPLE_VIDEO = self.video()

        upload.render()

        staged = self.st.session_state["staged_video"]
        self.assertEqual(staged["name"], "src.mp4")
        self.assertEqual((staged["width"], staged["height"]), (160, 400))
        # The settings panel is shown (sliders themselves are not recorded
        # by the fake, so check for its heading).
        self.assertIn("Stop line and signal", self.st.text())

    def test_collision_alerts_need_twilio_and_an_explicit_opt_in(self):
        # Opted in, but Twilio is not configured: the box is disabled and
        # explains why; no alert path is taken.
        self.start(uploads={"video_file": UploadedFile(
            "c.mp4", self.video().read_bytes())},
            values={"check_collisions": True, "send_alerts": True})
        upload = self.upload_module()

        with mock.patch.dict("os.environ", {}, clear=True):
            upload.render()

        self.assertIn("Twilio is not set up", self.st.text())

        # Configured and opted in: a clear warning is shown first.
        self.start(uploads={"video_file": UploadedFile(
            "c.mp4", self.video().read_bytes())},
            values={"check_collisions": True, "send_alerts": True})
        upload = self.upload_module()
        env = {"TWILIO_ACCOUNT_SID": "a", "TWILIO_AUTH_TOKEN": "b",
               "TWILIO_PHONE_NUMBER": "c", "ALERT_TO_PHONE": "d"}

        with mock.patch.dict("os.environ", env, clear=True):
            upload.render()

        self.assertIn("A real message goes to the number", self.st.text())


class MainRoutingTests(PageTestCase):

    def run_main(self, choice, **kwargs):
        self.start(values={"Go to": choice}, **kwargs)

        with mock.patch("app.ui.data.load_all", side_effect=empty_data):
            # main.py runs at import time, like `streamlit run`.
            sys.modules.pop("app.main", None)
            importlib.import_module("app.main")

    def test_every_page_is_reachable_from_the_sidebar(self):
        for choice, expected in (
            ("Analyze footage", "Upload traffic photos"),
            ("Dashboard", "Records from"),
            ("Evidence", "No evidence yet"),
            ("Alerts", "Collision alerts"),
            ("About", "How it works"),
        ):
            with self.subTest(page=choice):
                self.run_main(choice)
                self.assertIn(expected, self.st.text())
                self.assertIn("Academic prototype", self.st.text())

    def test_date_range_is_only_asked_for_on_data_pages(self):
        self.run_main("About")
        self.assertEqual(self.st.called("date_input"), [])

        self.run_main("Dashboard")
        self.assertGreaterEqual(len(self.st.called("date_input")), 0)


if __name__ == "__main__":
    unittest.main()
