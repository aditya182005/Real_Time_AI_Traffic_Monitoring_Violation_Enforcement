import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import cameras
from app.analysis import VideoSettings


class CameraProfileTests(unittest.TestCase):
    def profiles(self, data):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "cams.json"
        path.write_text(json.dumps(data))

        return str(path)

    def test_profile_overrides_and_sets_camera_id(self):
        path = self.profiles({"NH-4": {
            "stop_line_pct": 62, "signal_mode": "lamp",
            "lamp_roi_pct": [82, 4, 90, 22], "check_speed": True,
            "speed_distance_m": 12.5, "speed_limit_kmh": 50}})
        s = cameras.settings_for("NH-4", path)

        self.assertEqual(s.camera_id, "NH-4")
        self.assertEqual(s.stop_line_pct, 62.0)
        self.assertEqual(s.lamp_roi_pct, (82.0, 4.0, 90.0, 22.0))
        self.assertTrue(s.check_speed)
        self.assertEqual(s.speed_distance_m, 12.5)
        self.assertEqual(s.red_seconds, VideoSettings().red_seconds)

    def test_bad_profiles_are_refused(self):
        path = self.profiles({
            "typo": {"stop_line": 60},
            "text": {"stop_line_pct": "60"},
            "flag": {"check_speed": "yes"},
            "roi": {"lamp_roi_pct": [1, 2, 3]},
            "run": {"send_alerts": True},
            "notdict": 5,
        })

        for name in ("typo", "text", "flag", "roi", "run", "notdict", "absent"):
            with self.assertRaises(cameras.ProfileError, msg=name):
                cameras.settings_for(name, path)

    def test_missing_or_broken_file(self):
        with mock.patch.dict("os.environ", {"CAMERAS_FILE": ""}):
            with self.assertRaises(cameras.ProfileError):
                cameras.load_profiles()

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "x.json"
            bad.write_text("{nope")

            with self.assertRaises(cameras.ProfileError):
                cameras.load_profiles(str(bad))

            with self.assertRaises(cameras.ProfileError):
                cameras.load_profiles(str(Path(tmp) / "missing.json"))

    def test_cli_applies_profile_and_reports_errors(self):
        import run_video

        path = self.profiles({"A": {"stop_line_pct": 33}})
        parser = run_video.build_parser()

        with mock.patch.dict("os.environ", {"CAMERAS_FILE": path}):
            args = parser.parse_args(["--profile", "A"])
            settings = cameras.settings_for(
                args.profile, base=run_video.settings_from_args(args))
            self.assertEqual((settings.stop_line_pct, settings.camera_id), (33.0, "A"))

            with self.assertRaises(SystemExit):
                run_video.main(["--profile", "nope", "--no-display"])


if __name__ == "__main__":
    unittest.main()
