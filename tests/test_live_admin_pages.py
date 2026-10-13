import importlib
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

cv2 = None
try:
    import cv2
except ImportError:  # pragma: no cover
    pass

from app import audit, live, paths
from app.analysis import VideoSettings
from app.violation import violation_logger as vl
from tests.fake_streamlit import FakeStreamlit, StopPage, install
from tests.test_live import ListCapture, wait_until
from tests.test_run_video_cli import CarMovingDown, FakeDetector


class PageCase(unittest.TestCase):

    CAMERAS = "Gate=rtsp://admin:pw123@10.0.0.9/s1"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

        for target, name, value in (
            (vl, "DB_PATH", self.dir / "t.db"),
            (audit, "DB_PATH", self.dir / "t.db"),
            (paths, "OUTPUT_DIR", self.dir / "outputs"),
            (live, "REGISTRY", live.MonitorRegistry()),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        patcher = mock.patch.dict(os.environ, {
            "LIVE_CAMERAS": self.CAMERAS, "APP_ENV": "production",
            "USERS_FILE": str(self.dir / "users.json")}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(live.REGISTRY.stop_all)

    def start(self, role="operator", **kwargs):
        st = FakeStreamlit(**kwargs)
        st.session_state["user"] = {"name": "tester", "role": role}
        self.addCleanup(install(st))
        self.st = st

        return st

    def ui(self, name):
        return importlib.import_module(f"app.ui.{name}")

    def finished_monitor(self, name="Gate"):
        monitor = live.LiveMonitor(
            VideoSettings(camera_id=name, save_to_db=False), name,
            "rtsp://x/y", FakeDetector(), CarMovingDown(),
            capture_factory=lambda s: ListCapture())
        live.REGISTRY._monitors[name] = monitor
        monitor.start()
        self.assertTrue(wait_until(lambda: not monitor.active))

        return monitor


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class LivePageTests(PageCase):

    def test_an_operator_sees_the_start_controls(self):
        st = self.start()
        self.ui("live_page").render()

        self.assertIn("No camera is running", st.text())
        self.assertEqual(
            [c for c in st.called("button") if c[2]["key"] == "live_start"]
            [0][2]["disabled"], False)

    def test_a_viewer_can_watch_but_not_start(self):
        st = self.start("viewer")
        self.ui("live_page").render()

        self.assertIn("can watch but not start", st.text())
        self.assertEqual(
            [c for c in st.called("button") if c[2]["key"] == "live_start"],
            [])

    def test_the_camera_password_is_never_shown(self):
        st = self.start()
        self.finished_monitor()
        self.ui("live_page").render()

        self.assertNotIn("pw123", st.text() + str(st.calls))

    def test_starting_a_camera_uses_the_configured_address(self):
        st = self.start(clicks={"live_start"})
        page = self.ui("live_page")
        started = {}

        def fake_start(name, source, settings, *args, **kwargs):
            started.update(name=name, source=source, settings=settings)

            return mock.Mock()

        tracker = types.ModuleType("app.tracking.tracker")
        tracker.VehicleTracker = CarMovingDown

        with mock.patch.object(page.upload, "_load_models",
                               return_value=(FakeDetector(), None)), \
                mock.patch.dict(sys.modules,
                                {"app.tracking.tracker": tracker}), \
                mock.patch.object(live.REGISTRY, "start", fake_start):
            page.render()

        self.assertEqual(started["name"], "Gate")
        self.assertEqual(started["source"], "rtsp://admin:pw123@10.0.0.9/s1")
        self.assertEqual(audit.recent()[0]["action"], "live_start")
        self.assertNotIn("pw123", str(audit.recent()))

    def test_a_refused_start_shows_the_reason(self):
        st = self.start(clicks={"live_start"})
        page = self.ui("live_page")
        tracker = types.ModuleType("app.tracking.tracker")
        tracker.VehicleTracker = CarMovingDown

        with mock.patch.object(page.upload, "_load_models",
                               return_value=(FakeDetector(), None)), \
                mock.patch.dict(sys.modules,
                                {"app.tracking.tracker": tracker}), \
                mock.patch.object(
                    live.REGISTRY, "start",
                    side_effect=live.LiveError("Gate is already running.")):
            page.render()

        self.assertIn("already running", [c for c in st.called("error")][0][1][0])

    def test_a_configured_camera_is_picked_by_name(self):
        self.start(values={"live_camera": "Gate"})

        self.assertEqual(
            self.ui("live_page")._pick_source(),
            ("Gate", "rtsp://admin:pw123@10.0.0.9/s1"))

    def test_free_form_addresses_are_refused_in_production(self):
        self.start(values={"live_camera": "Other address or webcam…",
                           "live_address": "rtsp://evil.example/x"})

        self.assertIsNone(self.ui("live_page")._pick_source())

    def test_free_form_addresses_work_on_a_developer_machine(self):
        with mock.patch.dict(os.environ, {"APP_ENV": ""}):
            self.start(values={"live_camera": "Other address or webcam…",
                               "live_address": "0"})

            self.assertEqual(self.ui("live_page")._pick_source(),
                             ("CAM-01", 0))

    def test_a_file_path_is_not_accepted_as_a_camera(self):
        with mock.patch.dict(os.environ, {"APP_ENV": ""}):
            st = self.start(values={"live_camera": "Other address or webcam…",
                                    "live_address": "/etc/passwd"})

            self.assertIsNone(self.ui("live_page")._pick_source())

        self.assertIn("must start with", st.text() + str(st.calls))

    def test_no_cameras_configured_explains_how(self):
        with mock.patch.dict(os.environ, {"LIVE_CAMERAS": ""}):
            st = self.start()
            self.ui("live_page").render()

        self.assertIn("LIVE_CAMERAS", st.text())

    def test_a_finished_run_is_reported_with_its_counts(self):
        self.finished_monitor()
        st = self.start("viewer")
        self.ui("live_page").render()
        text = st.text()

        self.assertIn("Gate", text)
        self.assertIn("Stopped", text)
        self.assertIn("Violations", text)
        self.assertEqual(
            [c for c in st.called("button") if "live_stop" in
             str(c[2]["key"])], [])

    def test_only_operators_get_a_stop_button(self):
        class Endless(ListCapture):
            def read(self):
                time.sleep(0.005)

                return True, super().frames[0] if False else __import__(
                    "numpy").zeros((400, 160, 3), "uint8")

        monitor = live.LiveMonitor(
            VideoSettings(save_to_db=False), "Gate", "rtsp://x/y",
            FakeDetector(), CarMovingDown(),
            capture_factory=lambda s: Endless())
        live.REGISTRY._monitors["Gate"] = monitor
        monitor.start()
        self.assertTrue(wait_until(lambda: monitor.state == "running"))

        for role, expected in (("viewer", 0), ("operator", 1)):
            st = self.start(role)
            self.ui("live_page").render()
            stops = [c for c in st.called("button")
                     if str(c[2]["key"]).startswith("live_stop")]

            self.assertEqual(len(stops), expected, role)

        monitor.stop()


class RegistryTests(unittest.TestCase):

    def make(self):
        registry = live.MonitorRegistry()
        self.addCleanup(registry.stop_all)

        return registry

    def start(self, registry, name):
        class Endless(ListCapture):
            def read(self):
                time.sleep(0.005)

                return True, __import__("numpy").zeros((400, 160, 3), "uint8")

        return registry.start(
            name, "rtsp://x/y", VideoSettings(save_to_db=False),
            FakeDetector(), CarMovingDown(),
            capture_factory=lambda s: Endless())

    @unittest.skipIf(cv2 is None, "OpenCV not installed")
    def test_one_name_cannot_run_twice_and_the_limit_applies(self):
        registry = self.make()

        with mock.patch.dict(os.environ, {"LIVE_MAX_CAMERAS": "1"}):
            self.start(registry, "A")

            with self.assertRaisesRegex(live.LiveError, "already running"):
                self.start(registry, "A")

            with self.assertRaisesRegex(live.LiveError, "Only 1"):
                self.start(registry, "B")

    @unittest.skipIf(cv2 is None, "OpenCV not installed")
    def test_a_stopped_camera_can_be_started_again(self):
        registry = self.make()

        with mock.patch.dict(os.environ, {"LIVE_MAX_CAMERAS": "2"}):
            first = self.start(registry, "A")
            self.start(registry, "B")
            registry.stop("A")

            self.assertFalse(first.active)
            second = self.start(registry, "A")

            self.assertIsNot(first, second)
            self.assertEqual(sorted(registry.names()), ["A", "B"])
            self.assertEqual(len(registry.snapshots()), 2)

    def test_max_cameras_setting_is_forgiving(self):
        for value, expected in (("3", 3), ("0", 1), ("x", 1), ("", 1)):
            with mock.patch.dict(os.environ, {"LIVE_MAX_CAMERAS": value}):
                self.assertEqual(live.max_cameras(), expected, value)


class AdminPageTests(PageCase):

    def test_admins_see_status_and_the_audit_log(self):
        audit.record("login_ok", user="alice", role="admin")
        st = self.start("admin")
        self.ui("admin").render()
        text = st.text()

        self.assertIn("database", text)
        self.assertIn("python -m app.health", text)
        self.assertEqual(len(st.called("dataframe")), 1)   # the audit table

    def test_others_are_turned_away(self):
        for role in ("viewer", "operator"):
            st = self.start(role)
            self.ui("admin").render()

            self.assertIn("cannot open the Admin page", st.text())
            self.assertNotIn("python -m app.health", st.text())


class MainNavigationTests(PageCase):

    def run_main(self, role):
        st = self.start(role)
        st.session_state["authenticated"] = True

        with mock.patch.dict(os.environ, {"APP_ENV": "production",
                                          "DASHBOARD_PASSWORD": "x"}):
            sys.modules.pop("app.main", None)

            try:
                importlib.import_module("app.main")
            except StopPage:
                pass

        radios = [c for c in st.called("radio") if c[1][0] == "Go to"]

        return st, radios[0][1][1]

    def test_the_admin_page_is_listed_for_admins_only(self):
        _, admin_pages = self.run_main("admin")
        _, operator_pages = self.run_main("operator")

        self.assertIn("Admin", admin_pages)
        self.assertNotIn("Admin", operator_pages)
        self.assertIn("Live camera", operator_pages)


if __name__ == "__main__":
    unittest.main()
