"""Read the signal state from the video itself.

Instead of a simulated signal, point this at the traffic lamp in the picture:
a small rectangle (given as percent of the frame) that contains the red and
green lights. Each frame, the lit colour inside it decides the state:

* red lit            -> ``RED``
* green or amber lit -> ``GREEN`` (crossing on amber is not flagged)
* nothing clearly lit -> keep the previous state

A change must be seen for ``confirm_frames`` frames in a row before it counts,
so a flicker or one bad frame does not flip the signal. Until the first
confirmed reading the state is ``GREEN``, so no red-light violation can be
recorded before the lamp has actually been seen red.

This works for a clear, fixed view of the lamp. It does not find the lamp by
itself, and glare, night blooming or a lamp that is too small will fool it.
Check the first minute of any new camera by eye.
"""

import numpy as np

VALID_STATES = ("RED", "GREEN")

# OpenCV hue runs 0-179. Red wraps around zero.
RED_HUES = ((0, 10), (165, 179))
GREEN_HUES = ((35, 95),)
AMBER_HUES = ((10, 35),)
MIN_SATURATION = 100
MIN_VALUE = 150
MIN_LIT_FRACTION = 0.02
MIN_LIT_PIXELS = 6
DOMINANCE = 1.5


class LampSignal:
    label = "from lamp"

    def __init__(self, roi_pct, confirm_frames=3):
        x1, y1, x2, y2 = (float(v) for v in roi_pct)

        if not (0 <= x1 < x2 <= 100 and 0 <= y1 < y2 <= 100):
            raise ValueError(
                "The lamp area must be x1,y1,x2,y2 in percent with "
                "x1<x2 and y1<y2.")

        self.roi_pct = (x1, y1, x2, y2)
        self.confirm_frames = max(1, int(confirm_frames))
        self.state = "GREEN"
        self.seen = False            # has a lit lamp been confirmed yet?
        self._candidate = None
        self._streak = 0

    # -- reading the picture ------------------------------------------------

    def _crop(self, frame):
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = self.roi_pct
        top, bottom = int(height * y1 / 100), max(int(height * y2 / 100), 1)
        left, right = int(width * x1 / 100), max(int(width * x2 / 100), 1)

        return frame[top:bottom, left:right]

    @staticmethod
    def _count(hue, mask, ranges):
        total = 0

        for low, high in ranges:
            total += int(np.count_nonzero(mask & (hue >= low) & (hue <= high)))

        return total

    def read(self, frame):
        """``'RED'``, ``'GREEN'`` or None for one frame (no smoothing)."""

        import cv2

        crop = self._crop(frame)

        if crop.size == 0:
            return None

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        lit = (sat >= MIN_SATURATION) & (val >= MIN_VALUE)
        need = max(MIN_LIT_PIXELS, MIN_LIT_FRACTION * hue.size)

        red = self._count(hue, lit, RED_HUES)
        go = self._count(hue, lit, GREEN_HUES + AMBER_HUES)

        if red >= need and red >= DOMINANCE * go:
            return "RED"

        if go >= need and go >= DOMINANCE * red:
            return "GREEN"

        return None

    # -- the signal interface the video processor uses ----------------------

    def observe(self, frame):
        reading = self.read(frame)

        if reading is None or reading == self.state and self.seen:
            self._candidate, self._streak = None, 0
            return

        if reading == self._candidate:
            self._streak += 1
        else:
            self._candidate, self._streak = reading, 1

        if self._streak >= self.confirm_frames:
            self.state = reading
            self.seen = True
            self._candidate, self._streak = None, 0

    def state_at(self, frame_number, fps):
        return self.state

    def describe(self):
        x1, y1, x2, y2 = self.roi_pct

        return f"Read from the lamp at {x1:g},{y1:g} to {x2:g},{y2:g} percent"
