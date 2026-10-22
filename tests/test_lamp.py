import unittest

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from app.analysis import VideoSettings, build_signal, validate_settings
from app.violation.lamp import LampSignal

RED = (0, 0, 255)       # BGR
GREEN = (0, 200, 0)
AMBER = (0, 190, 255)


def frame_with(colour=None, size=(200, 100)):
    """Dark frame; a lamp disc at x 80-90 %, y 5-25 % when colour is given."""

    frame = np.zeros((size[0], size[1], 3), np.uint8)

    if colour is not None:
        cv2.circle(frame, (85, 30), 8, colour, -1)

    return frame


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class LampTests(unittest.TestCase):
    roi = (70, 5, 100, 40)

    def lamp(self, **kw):
        return LampSignal(self.roi, **kw)

    def test_reads_each_colour(self):
        lamp = self.lamp()

        self.assertEqual(lamp.read(frame_with(RED)), "RED")
        self.assertEqual(lamp.read(frame_with(GREEN)), "GREEN")
        self.assertEqual(lamp.read(frame_with(AMBER)), "GREEN")
        self.assertIsNone(lamp.read(frame_with(None)))

    def test_starts_green_so_nothing_is_flagged_before_the_lamp_is_seen(self):
        lamp = self.lamp()
        lamp.observe(frame_with(None))

        self.assertEqual(lamp.state_at(1, 30), "GREEN")
        self.assertFalse(lamp.seen)

    def test_needs_confirmation_before_switching(self):
        lamp = self.lamp(confirm_frames=3)

        for _ in range(2):
            lamp.observe(frame_with(RED))

        self.assertEqual(lamp.state, "GREEN")
        lamp.observe(frame_with(RED))
        self.assertEqual(lamp.state, "RED")

    def test_flicker_and_dark_frames_do_not_flip_it(self):
        lamp = self.lamp(confirm_frames=3)

        for _ in range(3):
            lamp.observe(frame_with(RED))

        for colour in (GREEN, None, GREEN, None, RED):
            lamp.observe(frame_with(colour))

        self.assertEqual(lamp.state, "RED")

        for _ in range(3):
            lamp.observe(frame_with(GREEN))

        self.assertEqual(lamp.state, "GREEN")

    def test_bad_roi_is_rejected(self):
        for roi in ((50, 5, 40, 20), (0, 0, 0, 0), (0, 0, 101, 10)):
            with self.assertRaises(ValueError):
                LampSignal(roi)

    def test_settings_validation_and_builder(self):
        settings = VideoSettings(signal_mode="lamp", lamp_roi_pct=self.roi)

        self.assertEqual(validate_settings(settings), [])
        self.assertIsInstance(build_signal(settings), LampSignal)
        self.assertTrue(validate_settings(VideoSettings(signal_mode="lamp")))


if __name__ == "__main__":
    unittest.main()
