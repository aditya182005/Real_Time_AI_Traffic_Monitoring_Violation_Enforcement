"""Click-to-calibrate: real distances from four known points on the road.

Mark the four corners of a rectangle on the road whose real width and length
you know (a lane segment between painted marks, a measured patch). A
homography maps image pixels to metres on the road plane, so the distance
between the two speed lines no longer rests on one tape-measure guess and
perspective is handled properly.

Limits: the four points must be on the flat road, not on a raised object;
the camera must not move afterwards; accuracy falls with the corner-clicking
error and with how far the speed lines are from the marked rectangle.
"""

import json
from pathlib import Path

import numpy as np


class CalibrationError(ValueError):
    """The calibration points or file are unusable."""


def _homography(source, target):
    """3x3 matrix mapping four ``source`` points to four ``target`` points."""

    rows, values = [], []

    for (x, y), (u, v) in zip(source, target):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        values.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values.append(v)

    try:
        solution = np.linalg.solve(np.array(rows, float), np.array(values, float))
    except np.linalg.LinAlgError as exc:
        raise CalibrationError(
            "These four points cannot define a plane (three on one line, or "
            "two the same). Click four separate corners.") from exc

    return np.append(solution, 1.0).reshape(3, 3)


class Calibration:

    def __init__(self, image_points, width_m, length_m):
        if len(image_points) != 4:
            raise CalibrationError("Exactly four image points are needed.")

        if width_m <= 0 or length_m <= 0:
            raise CalibrationError("Width and length must be above zero.")

        self.image_points = [(float(x), float(y)) for x, y in image_points]
        self.width_m = float(width_m)
        self.length_m = float(length_m)

        # Order: near-left, near-right, far-right, far-left (any rectangle
        # order works if you stay consistent; the distances are the same).
        world = [(0, 0), (self.width_m, 0),
                 (self.width_m, self.length_m), (0, self.length_m)]
        self._matrix = _homography(self.image_points, world)

    def to_world(self, x, y):
        u, v, w = self._matrix @ np.array([x, y, 1.0])

        if abs(w) < 1e-12:
            raise CalibrationError("That point is on the horizon.")

        return u / w, v / w

    def distance_m(self, point_a, point_b):
        ax, ay = self.to_world(*point_a)
        bx, by = self.to_world(*point_b)

        return float(np.hypot(ax - bx, ay - by))

    def distance_between_rows(self, row_a, row_b):
        """Road distance between two pixel rows, along the marked area's
        centre line."""

        xs = [p[0] for p in self.image_points]
        x = sum(xs) / 4.0

        return self.distance_m((x, row_a), (x, row_b))

    def to_dict(self):
        return {"image_points": self.image_points,
                "real_size_m": [self.width_m, self.length_m]}

    def save(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2),
                              encoding="utf-8")

    @classmethod
    def from_dict(cls, data):
        try:
            width, length = data["real_size_m"]

            return cls(data["image_points"], width, length)
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, CalibrationError):
                raise

            raise CalibrationError(
                "A calibration file needs image_points (4 x [x, y]) and "
                "real_size_m ([width, length]).") from exc

    @classmethod
    def load(cls, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise CalibrationError(f"Cannot read {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CalibrationError(f"{path} is not valid JSON: {exc}") from exc

        return cls.from_dict(data)
