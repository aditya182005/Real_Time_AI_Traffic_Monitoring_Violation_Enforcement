"""Zone-based rules: illegal parking, crossing encroachment, restricted lane,
and triple riding. Plain Python, so every rule is testable without a model.

Zones come from a small JSON file (``--zones zones.json`` in run_video.py).
Points are pixels in the video frame::

    {
      "no_parking": {"polygon": [[100,300],[400,300],[400,500],[100,500]],
                     "seconds": 30},
      "crossing":   {"y_top": 380, "y_bottom": 440},
      "restricted_lane": {"polygon": [[0,300],[200,300],[200,700],[0,700]],
                          "allowed": ["motorcycle"]},
      "triple_riding": true
    }

Every rule needs a vehicle to be *tracked*, and acts only after the condition
has held for a while, so one noisy frame cannot create a violation.
"""

import json
from pathlib import Path

from app.violation.helmet import head_belongs_to

KINDS = ("illegal_parking", "crossing_encroachment", "wrong_lane",
         "triple_riding")


class ZoneConfigError(ValueError):
    """The zones file is missing or malformed."""


def point_in_polygon(x, y, polygon):
    """Ray-casting test. ``polygon`` is a list of (x, y) points."""

    inside = False
    count = len(polygon)

    for i in range(count):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % count]

        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1

            if x < crossing:
                inside = not inside

    return inside


def _polygon(value, where):
    try:
        points = [(float(p[0]), float(p[1])) for p in value]
    except (TypeError, ValueError, IndexError) as exc:
        raise ZoneConfigError(f"{where}: polygon must be [[x, y], ...].") from exc

    if len(points) < 3:
        raise ZoneConfigError(f"{where}: a polygon needs at least 3 points.")

    return points


class ZoneConfig:
    """The validated contents of a zones file."""

    def __init__(self, no_parking=None, crossing=None, restricted_lane=None,
                 triple_riding=False):
        self.no_parking = no_parking          # {"polygon", "seconds"}
        self.crossing = crossing              # {"y_top", "y_bottom"}
        self.restricted_lane = restricted_lane  # {"polygon", "allowed"}
        self.triple_riding = bool(triple_riding)

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict):
            raise ZoneConfigError("The zones file must contain a JSON object.")

        unknown = set(data) - {"no_parking", "crossing", "restricted_lane",
                               "triple_riding"}

        if unknown:
            raise ZoneConfigError(
                f"Unknown zone type(s): {', '.join(sorted(unknown))}.")

        parking = data.get("no_parking")

        if parking is not None:
            seconds = parking.get("seconds", 30)

            if not isinstance(seconds, (int, float)) or seconds <= 0:
                raise ZoneConfigError("no_parking.seconds must be above 0.")

            parking = {"polygon": _polygon(parking.get("polygon"),
                                           "no_parking"),
                       "seconds": float(seconds)}

        crossing = data.get("crossing")

        if crossing is not None:
            try:
                top, bottom = float(crossing["y_top"]), float(crossing["y_bottom"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ZoneConfigError(
                    "crossing needs numeric y_top and y_bottom.") from exc

            if top >= bottom:
                raise ZoneConfigError("crossing.y_top must be above y_bottom.")

            crossing = {"y_top": top, "y_bottom": bottom}

        lane = data.get("restricted_lane")

        if lane is not None:
            allowed = lane.get("allowed")

            if (not isinstance(allowed, list) or not allowed
                    or not all(isinstance(a, str) for a in allowed)):
                raise ZoneConfigError(
                    "restricted_lane.allowed must list vehicle classes.")

            lane = {"polygon": _polygon(lane.get("polygon"),
                                        "restricted_lane"),
                    "allowed": set(allowed)}

        return cls(parking, crossing, lane, data.get("triple_riding", False))

    @classmethod
    def load(cls, path):
        file = Path(path).expanduser()

        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ZoneConfigError(f"Cannot read zones file {file}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ZoneConfigError(
                f"Zones file {file} is not valid JSON: {exc}") from exc

        return cls.parse(data)

    @property
    def active(self):
        return bool(self.no_parking or self.crossing or self.restricted_lane
                    or self.triple_riding)


def _foot(bbox):
    """The point where a vehicle touches the road: bottom centre."""

    return (bbox[0] + bbox[2]) / 2, bbox[3]


class ParkingMonitor:
    """Flags a vehicle that stays inside a no-parking polygon, nearly still."""

    def __init__(self, polygon, seconds, still_px=25):
        self.polygon = polygon
        self.seconds = seconds
        self.still_px = still_px
        self._since = {}       # track_id -> (time, x, y) when it settled
        self._reported = set()

    def update(self, track_id, bbox, now_seconds):
        if track_id in self._reported:
            return False

        x, y = _foot(bbox)

        if not point_in_polygon(x, y, self.polygon):
            self._since.pop(track_id, None)
            return False

        start = self._since.get(track_id)

        if start is None or (abs(x - start[1]) > self.still_px
                             or abs(y - start[2]) > self.still_px):
            self._since[track_id] = (now_seconds, x, y)   # moved: restart
            return False

        if now_seconds - start[0] >= self.seconds:
            self._reported.add(track_id)
            return True

        return False


class CrossingMonitor:
    """Flags a vehicle standing on the zebra crossing while the signal is RED.

    "Standing" means its position barely changed for ``hold`` seconds, so a
    car just rolling through on green, or a slow one crossing before red, is
    left alone.
    """

    def __init__(self, y_top, y_bottom, hold=2.0, still_px=15):
        self.y_top = y_top
        self.y_bottom = y_bottom
        self.hold = hold
        self.still_px = still_px
        self._since = {}
        self._reported = set()

    def update(self, track_id, bbox, signal_state, now_seconds):
        if track_id in self._reported:
            return False

        x, y = _foot(bbox)
        on_band = self.y_top <= y <= self.y_bottom

        if not (on_band and signal_state == "RED"):
            self._since.pop(track_id, None)
            return False

        start = self._since.get(track_id)

        if start is None or abs(y - start[1]) > self.still_px:
            self._since[track_id] = (now_seconds, y)
            return False

        if now_seconds - start[0] >= self.hold:
            self._reported.add(track_id)
            return True

        return False


class RestrictedLane:
    """Flags a vehicle class that is not allowed in a lane (bus lane, etc.)."""

    def __init__(self, polygon, allowed, persist=5):
        self.polygon = polygon
        self.allowed = set(allowed)
        self.persist = persist
        self._streak = {}
        self._reported = set()

    def update(self, track_id, bbox, class_name):
        if track_id in self._reported:
            return False

        x, y = _foot(bbox)

        if (class_name in self.allowed
                or not point_in_polygon(x, y, self.polygon)):
            self._streak[track_id] = 0
            return False

        self._streak[track_id] = self._streak.get(track_id, 0) + 1

        if self._streak[track_id] >= self.persist:
            self._reported.add(track_id)
            return True

        return False


class TripleRiding:
    """Flags a motorcycle carrying three or more people.

    Uses the heads the helmet model already finds (helmet or no helmet), so
    it needs no extra model. A head counts when it sits on this motorcycle;
    the largest head count seen over ``confirm`` frames decides.
    """

    def __init__(self, riders=3, confirm=3, min_confidence=0.5):
        self.riders = riders
        self.confirm = confirm
        self.min_confidence = min_confidence
        self._streak = {}
        self._reported = set()

    def update(self, track_id, bike_box, heads):
        if track_id in self._reported:
            return False

        count = sum(
            1 for h in heads
            if h["confidence"] >= self.min_confidence
            and head_belongs_to(h["bbox"], bike_box)
        )

        self._streak[track_id] = (
            self._streak.get(track_id, 0) + 1 if count >= self.riders else 0)

        if self._streak[track_id] >= self.confirm:
            self._reported.add(track_id)
            return True

        return False
