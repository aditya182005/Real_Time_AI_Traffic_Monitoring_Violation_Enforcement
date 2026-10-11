import unittest

import numpy as np

from app.analysis import (
    VideoSettings,
    build_processor,
    build_signal,
    pixel_col,
    pixel_row,
    validate_settings,
)
from app.annotate import draw_calibration


class SettingsTests(unittest.TestCase):

    def test_percentages_become_pixels(self):
        self.assertEqual(pixel_row(1080, 60), 648)
        self.assertEqual(pixel_col(1920, 50), 960)
        self.assertEqual(pixel_row(400, 0), 0)

    def test_valid_defaults_have_no_problems(self):
        self.assertEqual(validate_settings(VideoSettings()), [])

    def test_problems_are_reported_in_plain_language(self):
        settings = VideoSettings(
            check_speed=True, speed_line_a_pct=50, speed_line_b_pct=50,
            check_wrong_way=True, lane_from_pct=60, lane_to_pct=60,
        )

        problems = validate_settings(settings)

        self.assertEqual(len(problems), 2)
        self.assertIn("speed line", problems[0].lower())

    def test_disabled_checks_are_not_validated(self):
        settings = VideoSettings(speed_line_a_pct=50, speed_line_b_pct=50,
                                 lane_from_pct=90, lane_to_pct=10)

        self.assertEqual(validate_settings(settings), [])

    def test_signal_modes(self):
        self.assertEqual(
            build_signal(VideoSettings(signal_mode="red")).state_at(1, 10),
            "RED")
        self.assertEqual(
            build_signal(VideoSettings(signal_mode="green")).state_at(1, 10),
            "GREEN")

        cycle = build_signal(VideoSettings(
            signal_mode="cycle", red_seconds=1, green_seconds=2))

        self.assertEqual(cycle.state_at(1, 10), "RED")
        self.assertEqual(cycle.state_at(11, 10), "GREEN")

    def test_build_processor_converts_settings_for_the_frame_size(self):
        settings = VideoSettings(
            camera_id="  CAM-5 ", stop_line_pct=50,
            check_speed=True, speed_line_a_pct=40, speed_line_b_pct=80,
            speed_distance_m=12, speed_limit_kmh=50,
            check_wrong_way=True, expected_direction="up",
            lane_from_pct=25, lane_to_pct=75,
            check_collisions=True, send_alerts=True, use_emergency=True,
        )
        emergency = object()

        processor = build_processor(
            settings, 1000, 800, detector=object(), tracker=object(),
            emergency_detector=emergency, evidence_dir="ev",
        )

        self.assertEqual(processor.stop_line_y, 400)
        self.assertEqual((processor.speed.line_a_y, processor.speed.line_b_y),
                         (320, 640))
        self.assertEqual(processor.speed.distance_m, 12.0)
        self.assertEqual(processor.speed.limit_kmh, 50.0)
        self.assertEqual(processor.wrong_way.expected, "up")
        self.assertEqual((processor.wrong_way.x_min, processor.wrong_way.x_max),
                         (250, 750))
        self.assertTrue(processor.detect_collisions)
        self.assertTrue(processor.send_collision_alerts)
        self.assertIs(processor.emergency_detector, emergency)
        self.assertEqual(processor.camera_id, "CAM-5")

    def test_checks_are_off_unless_enabled(self):
        processor = build_processor(
            VideoSettings(), 1000, 800, object(), object(), object(), "ev")

        self.assertIsNone(processor.speed)
        self.assertIsNone(processor.wrong_way)
        self.assertFalse(processor.detect_collisions)
        self.assertIsNone(processor.emergency_detector)

    def test_alerts_need_collision_checking_too(self):
        settings = VideoSettings(check_collisions=False, send_alerts=True)

        processor = build_processor(
            settings, 100, 100, object(), object(), None, "ev")

        self.assertFalse(processor.send_collision_alerts)

    def test_blank_camera_name_falls_back(self):
        processor = build_processor(
            VideoSettings(camera_id="   "), 100, 100, object(), object(),
            None, "ev")

        self.assertEqual(processor.camera_id, "CAM-01")


class CalibrationOverlayTests(unittest.TestCase):

    def test_overlay_draws_on_a_copy(self):
        frame = np.zeros((200, 300, 3), dtype=np.uint8)

        preview = draw_calibration(frame, 120, speed_lines=(60, 150),
                                   lane=(50, 150))

        self.assertEqual(preview.shape, frame.shape)
        self.assertEqual(int(frame.sum()), 0)            # original untouched
        self.assertGreater(int(preview[120, 200].sum()), 0)   # stop line
        self.assertGreater(int(preview[60, 200].sum()), 0)    # speed line A
        self.assertGreater(int(preview[100, 100].sum()), 0)   # shaded lane
        self.assertEqual(int(preview[100, 250].sum()), 0)     # outside lane


if __name__ == "__main__":
    unittest.main()
