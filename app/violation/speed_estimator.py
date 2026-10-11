"""Two-line speed estimation (pure Python).

A vehicle's speed is the known real-world distance between two lines divided
by the time it takes to cross both. It is only as accurate as that distance:
measure it on the road (e.g. between two lane-marking dashes or poles) and
keep the camera fixed. Direction does not matter, so traffic moving either
way is measured.
"""


def _crossed(previous, current, line):
    return (previous < line <= current) or (previous > line >= current)


class SpeedEstimator:

    def __init__(self, line_a_y, line_b_y, distance_m, x_min=None, x_max=None):
        if distance_m <= 0:
            raise ValueError("The distance between the lines must be positive.")

        if line_a_y == line_b_y:
            raise ValueError("The two measurement lines must be different.")

        self.line_a_y = line_a_y
        self.line_b_y = line_b_y
        self.distance_m = float(distance_m)
        self.x_min = x_min
        self.x_max = x_max

        self.previous_y = {}
        self.crossings = {}     # track_id -> {"a": frame, "b": frame}
        self.speeds = {}        # track_id -> km/h (measured once)

    def _in_lane(self, center_x):
        if self.x_min is not None and center_x < self.x_min:
            return False

        if self.x_max is not None and center_x > self.x_max:
            return False

        return True

    def update(self, track_id, center_x, y, frame_number, fps):
        """Feed one observation (y = bottom of the box).

        Returns the speed in km/h the moment a vehicle completes the
        measurement, otherwise None. Each vehicle is measured once.
        """

        previous = self.previous_y.get(track_id)
        self.previous_y[track_id] = y

        if previous is None or track_id in self.speeds:
            return None

        if not self._in_lane(center_x):
            return None

        seen = self.crossings.setdefault(track_id, {})

        for name, line in (("a", self.line_a_y), ("b", self.line_b_y)):
            if name not in seen and _crossed(previous, y, line):
                seen[name] = frame_number

        if "a" in seen and "b" in seen:
            frames = abs(seen["b"] - seen["a"])

            if frames == 0 or not fps:
                return None

            speed = self.distance_m / (frames / float(fps)) * 3.6
            self.speeds[track_id] = speed

            return speed

        return None
