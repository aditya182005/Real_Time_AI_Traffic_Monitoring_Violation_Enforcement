"""Collision heuristic (pure Python, no OpenCV / YOLO needed).

A "possible collision" requires ALL of:
  1. two tracked vehicles whose boxes overlap (IoU >= threshold),
  2. the overlap persists for several consecutive frames, and
  3. at least one of the two vehicles shows an abrupt drop in speed.

Condition 3 follows the project plan (sudden overlap + abrupt velocity drop).
It is what separates a crash from ordinary congestion or one car passing
another in perspective: in queued traffic the vehicles are already slow, and
when passing they do not suddenly stop.

This is still a heuristic: always have a person verify an alert.
"""

import math
from collections import deque

IOU_THRESHOLD = 0.15
PERSISTENCE_FRAMES = 3
HISTORY_FRAMES = 8          # centre positions remembered per vehicle
MIN_APPROACH_SPEED = 3.0    # px/frame; slower vehicles count as already stopped
DROP_RATIO = 0.4            # current speed <= 40% of earlier speed = abrupt drop
DROP_LOOKBACK_FRAMES = 10   # a drop this recent still counts for an overlap
STALE_AFTER_FRAMES = 60     # forget vehicles not seen for this long


def calculate_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    x1 = max(ax1, bx1)
    y1 = max(ay1, by1)
    x2 = min(ax2, bx2)
    y2 = min(ay2, by2)

    intersection = max(0, x2 - x1) * max(0, y2 - y1)

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)

    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


class CollisionHeuristic:

    def __init__(
        self,
        iou_threshold=IOU_THRESHOLD,
        persistence_frames=PERSISTENCE_FRAMES,
        require_velocity_drop=True,
        min_approach_speed=MIN_APPROACH_SPEED,
        drop_ratio=DROP_RATIO,
        drop_lookback=DROP_LOOKBACK_FRAMES,
    ):
        self.iou_threshold = iou_threshold
        self.persistence_frames = persistence_frames
        self.require_velocity_drop = require_velocity_drop
        self.min_approach_speed = min_approach_speed
        self.drop_ratio = drop_ratio
        self.drop_lookback = drop_lookback

        self.frame = 0
        self.history = {}        # track_id -> deque of (cx, cy)
        self.last_seen = {}      # track_id -> frame
        self.last_drop = {}      # track_id -> frame of latest abrupt drop
        self.overlap_counts = {}  # pair -> consecutive overlapping frames
        self.reported_pairs = set()

    # -- speed handling ---------------------------------------------------

    def _record_position(self, track_id, box):
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0

        history = self.history.setdefault(
            track_id, deque(maxlen=HISTORY_FRAMES)
        )
        history.append((cx, cy))
        self.last_seen[track_id] = self.frame

    def _steps(self, track_id):
        points = list(self.history.get(track_id, ()))

        return [
            math.dist(points[i], points[i + 1])
            for i in range(len(points) - 1)
        ]

    def _abrupt_drop(self, track_id):
        steps = self._steps(track_id)

        # Need a few steps of "before" and 2 of "now".
        if len(steps) < 4:
            return False

        earlier = steps[:-2]
        now = steps[-2:]

        earlier_speed = sum(earlier) / len(earlier)
        current_speed = sum(now) / len(now)

        return (
            earlier_speed >= self.min_approach_speed
            and current_speed <= self.drop_ratio * earlier_speed
        )

    def _drop_seen_recently(self, track_id):
        frame = self.last_drop.get(track_id)

        return (
            frame is not None
            and self.frame - frame <= self.drop_lookback
        )

    # -- main entry -------------------------------------------------------

    def update(self, vehicles):
        """Feed one frame of ``(track_id, (x1, y1, x2, y2))`` pairs.

        Returns newly confirmed ``(pair, box_a, box_b)`` tuples, each pair
        reported at most once.
        """

        self.frame += 1

        boxes = {}

        for track_id, box in vehicles:
            track_id = int(track_id)
            boxes[track_id] = tuple(box)
            self._record_position(track_id, box)

            if self._abrupt_drop(track_id):
                self.last_drop[track_id] = self.frame

        active_pairs = set()
        confirmed = []
        ids = sorted(boxes)

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id_a, id_b = ids[i], ids[j]
                pair = (id_a, id_b)

                if calculate_iou(boxes[id_a], boxes[id_b]) < self.iou_threshold:
                    continue

                active_pairs.add(pair)
                self.overlap_counts[pair] = (
                    self.overlap_counts.get(pair, 0) + 1
                )

                if pair in self.reported_pairs:
                    continue

                if self.overlap_counts[pair] < self.persistence_frames:
                    continue

                if self.require_velocity_drop and not (
                    self._drop_seen_recently(id_a)
                    or self._drop_seen_recently(id_b)
                ):
                    continue

                self.reported_pairs.add(pair)
                confirmed.append((pair, boxes[id_a], boxes[id_b]))

        # Overlap must be consecutive: reset pairs that separated.
        for pair in list(self.overlap_counts):
            if pair not in active_pairs:
                del self.overlap_counts[pair]

        self._forget_stale()

        return confirmed

    def _forget_stale(self):
        for track_id in list(self.last_seen):
            if self.frame - self.last_seen[track_id] > STALE_AFTER_FRAMES:
                self.last_seen.pop(track_id, None)
                self.history.pop(track_id, None)
                self.last_drop.pop(track_id, None)
