import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

import check_setup
from check_setup import FAIL, OK, WARN


def statuses(checks):
    return {c.name: c.status for c in checks}


class FakeDetector:
    def __init__(self, found=2, fail=False):
        self.found, self.fail = found, fail

    def detect(self, frame, conf=None):
        if self.fail:
            raise RuntimeError("weights could not be downloaded")

        return [{"class_id": 2, "class_name": "car", "confidence": 0.9,
                 "bbox": (10, 10, 50, 50)}] * self.found


class FakeTracker:
    def __init__(self, fail=False):
        self.fail = fail

    def update(self, detections):
        if self.fail:
            raise ValueError("bad detections")

        return SimpleNamespace(xyxy=np.zeros((len(detections), 4)))


class PackageTests(unittest.TestCase):

    def test_missing_required_package_fails_with_the_fix(self):
        with mock.patch.object(check_setup, "_has_module",
                               side_effect=lambda m: m != "streamlit"):
            checks = check_setup.check_packages()

        by_name = {c.name: c for c in checks}
        self.assertEqual(by_name["streamlit"].status, FAIL)
        self.assertIn("pip install -r requirements.txt",
                      by_name["streamlit"].fix)
        self.assertEqual(by_name["numpy"].status, OK)

    def test_missing_twilio_is_only_a_warning(self):
        with mock.patch.object(check_setup, "_has_module",
                               side_effect=lambda m: m != "twilio"):
            checks = check_setup.check_packages()

        self.assertEqual(statuses(checks)["twilio"], WARN)
        self.assertNotIn(FAIL, statuses(checks).values())

    def test_old_python_fails(self):
        with mock.patch.object(check_setup.sys, "version_info",
                               (3, 8, 0, "final", 0)):
            self.assertEqual(check_setup.check_python()[0].status, FAIL)


class FileAndSettingTests(unittest.TestCase):

    def test_missing_model_and_video_are_warnings(self):
        with tempfile.TemporaryDirectory() as root:
            checks = statuses(check_setup.check_files(root))

        self.assertEqual(checks["Sample video"], WARN)
        self.assertEqual(checks["Emergency-vehicle model"], WARN)

    def test_present_files_are_ok(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("data/videos/traffic.mp4",
                         "models/emergency_vehicle.pt"):
                path = Path(root) / name
                path.parent.mkdir(parents=True)
                path.write_bytes(b"x")

            checks = statuses(check_setup.check_files(root))

        self.assertEqual(set(checks.values()), {OK})

    def test_unwritable_folder_fails(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch("check_setup.tempfile.NamedTemporaryFile",
                           side_effect=PermissionError(13, "Permission denied")):
            checks = statuses(check_setup.check_writable(root))

        self.assertEqual(set(checks.values()), {FAIL})

    def test_twilio_unset_valid_and_invalid(self):
        env = {"TWILIO_ACCOUNT_SID": "AC" + "1" * 32,
               "TWILIO_AUTH_TOKEN": "token",
               "TWILIO_PHONE_NUMBER": "+14155550123",
               "ALERT_TO_PHONE": "+919876543210"}

        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                check_setup.check_twilio_settings()[0].status, WARN)

        with mock.patch.dict("os.environ", env, clear=True):
            result = check_setup.check_twilio_settings()
            self.assertEqual(result[0].status, OK)
            # The report must never contain the secrets.
            text = check_setup.format_report(result)
            self.assertNotIn("token", text.replace("Auth Token", ""))
            self.assertNotIn("+919876543210", text)

        bad = dict(env, ALERT_TO_PHONE="98765")
        with mock.patch.dict("os.environ", bad, clear=True):
            self.assertEqual(
                check_setup.check_twilio_settings()[0].status, WARN)


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class SmokeTestTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data" / "images").mkdir(parents=True)
        cv2.imwrite(str(self.root / "data" / "images" / "test.jpg"),
                    np.zeros((120, 200, 3), np.uint8))

    def test_everything_works(self):
        checks = check_setup.smoke_test(
            self.root, detector=FakeDetector(2), tracker=FakeTracker())
        by_name = statuses(checks)

        self.assertEqual(by_name["Vehicle detection"], OK)
        self.assertEqual(by_name["Vehicle tracking"], OK)
        self.assertEqual(by_name["Emergency detection"], WARN)  # no weights
        self.assertIn("2 vehicle", checks[0].detail)

    def test_detection_failure_is_reported_with_the_cause(self):
        checks = check_setup.smoke_test(
            self.root, detector=FakeDetector(fail=True))

        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, FAIL)
        self.assertIn("could not be downloaded", checks[0].detail)
        self.assertIn("internet", checks[0].fix)

    def test_tracker_failure_does_not_hide_detection_success(self):
        checks = check_setup.smoke_test(
            self.root, detector=FakeDetector(), tracker=FakeTracker(fail=True))
        by_name = statuses(checks)

        self.assertEqual(by_name["Vehicle detection"], OK)
        self.assertEqual(by_name["Vehicle tracking"], FAIL)

    def test_emergency_model_is_exercised_when_present(self):
        emergency = FakeDetector(1)
        checks = check_setup.smoke_test(
            self.root, detector=FakeDetector(), tracker=FakeTracker(),
            emergency=emergency)

        self.assertEqual(statuses(checks)["Emergency detection"], OK)

    def test_missing_test_image_skips_instead_of_failing(self):
        (self.root / "data" / "images" / "test.jpg").unlink()
        checks = check_setup.smoke_test(self.root, detector=FakeDetector())

        self.assertEqual(checks[0].status, WARN)


class MainTests(unittest.TestCase):

    def run_main(self, argv, checks, smoke=()):
        out = io.StringIO()

        with mock.patch.object(check_setup, "quick_checks",
                               return_value=list(checks)), \
                mock.patch.object(check_setup, "smoke_test",
                                  return_value=list(smoke)) as smoke_mock, \
                contextlib.redirect_stdout(out):
            code = check_setup.main(argv)

        return code, out.getvalue(), smoke_mock

    def test_exit_status_reflects_failures(self):
        code, text, _ = self.run_main(
            [], [check_setup.Check(OK, "a"),
                 check_setup.Check(FAIL, "b", "broken", "do this")])

        self.assertEqual(code, 1)
        self.assertIn("[FAIL] b: broken", text)
        self.assertIn("-> do this", text)

    def test_warnings_alone_still_succeed(self):
        code, text, _ = self.run_main([], [check_setup.Check(WARN, "a")])

        self.assertEqual(code, 0)
        self.assertIn("Ready to run", text)

    def test_full_runs_the_smoke_test_only_when_asked(self):
        _, _, smoke = self.run_main([], [check_setup.Check(OK, "a")])
        smoke.assert_not_called()

        _, _, smoke = self.run_main(["--full"], [check_setup.Check(OK, "a")])
        smoke.assert_called_once()

    def test_full_is_skipped_when_required_packages_are_missing(self):
        code, text, smoke = self.run_main(
            ["--full"], [check_setup.Check(FAIL, "ultralytics", "missing")])

        smoke.assert_not_called()
        self.assertIn("skipped because required packages are missing", text)
        self.assertEqual(code, 1)

    def test_output_is_plain_ascii_for_windows_consoles(self):
        _, text, _ = self.run_main(
            [], [check_setup.Check(WARN, "a", "detail", "fix")])

        text.encode("ascii")     # raises if any emoji or symbol slipped in


if __name__ == "__main__":
    unittest.main()
