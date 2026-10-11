"""Wrong-way detection from tracked vehicle positions (pure Python).

A vehicle is flagged when its box has travelled against the expected
direction of traffic for a clear distance, and keeps doing so for a few
frames. Requiring real travel (not just a one-pixel jitter) and persistence
keeps tracker noise from producing violations.

``expected`` is the direction of normal traffic in the image:
  "down" - vehicles approach the camera (y grows),
  "up"   - vehicles move away from the camera (y shrinks).

Two-way roads: restrict the check to one carriageway with ``x_min`` /
``x_max`` (pixels), otherwise the oncoming lane would be flagged.
"""

from collections import deque

MIN_TRAVEL_PX = 40
WINDOW_FRAMES = 15
MIN_SAMPLES = 8
PERSIST_FRAMES = 3


class WrongWayDetector:

    def __init__(
        self,
        expected="down",
        min_travel_px=MIN_TRAVEL_PX,
        window=WINDOW_FRAMES,
        persist=PERSIST_FRAMES,
        x_min=None,
        x_max=None,
    ):
        if expected not in ("down", "up"):
            raise ValueError("expected must be 'down' or 'up'")

        self.expected = expected
        self.min_travel_px = min_travel_px
        self.window = window
        self.persist = persist
        self.x_min = x_min
        self.x_max = x_max

        self.history = {}      # track_id -> deque of y positions
        self.streaks = {}      # track_id -> consecutive wrong-way frames
        self.reported = set()

    def _in_lane(self, center_x):
        if self.x_min is not None and center_x < self.x_min:
            return False

        if self.x_max is not None and center_x > self.x_max:
            return False

        return True

    def update(self, track_id, center_x, y):
        """Feed one observation. True the first time a vehicle is flagged."""

        if track_id in self.reported or not self._in_lane(center_x):
            return False

        history = self.history.setdefault(track_id, deque(maxlen=self.window))
        history.append(y)

        if len(history) < MIN_SAMPLES:
            return False

        travel = history[-1] - history[0]
        against = (
            travel <= -self.min_travel_px
            if self.expected == "down"
            else travel >= self.min_travel_px
        )

        self.streaks[track_id] = self.streaks.get(track_id, 0) + 1 if against else 0

        if self.streaks[track_id] >= self.persist:
            self.reported.add(track_id)
            return True

        return False
