"""Build the demo video that triggers every check once.

    python scripts/make_demo_video.py

Writes ``data/videos/demo_all_checks.mp4`` and
``data/videos/demo_all_checks_truth.csv`` from the pictures in
``data/samples``. Vehicles from those photos are driven across a
plain road on a script, so you know exactly what should happen:

  * a car runs the red light,
  * a van crosses on green (no violation),
  * a car speeds,
  * a car drives the wrong way,
  * a car hits a stopped van (possible collision),
  * an ambulance, a fire truck and a police car appear (emergency vehicles).

The ``_truth.csv`` file is not typed by hand: the script plays its own
scripted vehicle positions through the real checks (a "perfect detector") and
records what they report. ``scripts/evaluate.py`` can then compare your real model
against it. Needs only OpenCV and NumPy.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:   # so the app package can be imported
    sys.path.insert(0, str(ROOT))
SAMPLES = ROOT / "data" / "samples"
VIDEO = ROOT / "data" / "videos" / "demo_all_checks.mp4"
TRUTH = ROOT / "data" / "videos" / "demo_all_checks_truth.csv"

W, H, FPS, SECONDS = 1000, 720, 30, 30
STOP_Y = int(H * 0.60)              # stop line (the default 60%)
LINE_A, LINE_B = int(H * 0.45), int(H * 0.75)
LANES = [120, 310, 500, 690, 880]
CAR_W = 190

# The settings that make these events happen (also printed at the end).
SETTINGS = ["--signal", "cycle", "--red-seconds", "6", "--green-seconds", "6",
            "--speed", "--distance-m", "10", "--speed-limit", "40",
            "--wrong-way", "--direction", "down", "--collisions",
            "--emergency"]


def cutout(path, box):
    """The vehicle from a photo, as a BGRA patch scaled to ``CAR_W`` wide.

    Photos with a labelled box are cropped to it; others lose a thin edge
    (the dataset's rotated copies have black corners). The whole vehicle is
    kept, because a detector needs to see all of it. Cutting it out of its
    background (GrabCut) removed wheels and left debris, so it is not done.
    """

    image = cv2.imread(str(path))

    if image is None:
        raise SystemExit(f"Cannot read {path}")

    height, width = image.shape[:2]

    if box:
        x, y, w, h = box
        pad = 0.04
        x1, x2 = (x - w / 2 - pad * w) * width, (x + w / 2 + pad * w) * width
        y1, y2 = (y - h / 2 - pad * h) * height, (y + h / 2 + pad * h) * height
    else:
        x1, x2, y1, y2 = 0.05 * width, 0.95 * width, 0.05 * height, 0.95 * height

    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(width, int(x2)), min(height, int(y2))
    image = image[y1:y2, x1:x2]
    scale = CAR_W / image.shape[1]
    image = cv2.resize(image, (CAR_W, max(60, int(image.shape[0] * scale))),
                       interpolation=cv2.INTER_AREA)

    return cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)


def paste(canvas, sprite, x_center, bottom):
    """Draw ``sprite`` with its bottom edge at ``bottom``; return the box."""

    h, w = sprite.shape[:2]
    x1, y1 = int(x_center - w / 2), int(bottom - h)
    x2, y2 = x1 + w, y1 + h
    cx1, cy1, cx2, cy2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)

    if cx1 >= cx2 or cy1 >= cy2:
        return None

    part = sprite[cy1 - y1:cy2 - y1, cx1 - x1:cx2 - x1]
    alpha = part[:, :, 3:4].astype(np.float32) / 255
    region = canvas[cy1:cy2, cx1:cx2].astype(np.float32)
    canvas[cy1:cy2, cx1:cx2] = (
        part[:, :, :3] * alpha + region * (1 - alpha)).astype(np.uint8)

    return (x1, y1, x2, y2)


def road():
    rng = np.random.default_rng(7)
    image = np.full((H, W, 3), 92, np.uint8)
    image += rng.integers(0, 7, (H, W, 3), dtype=np.uint8)

    for x in range(25, W, 190):
        cv2.line(image, (x, 0), (x, H), (150, 150, 150), 2)

    for y in range(0, H, 60):
        for x in (215, 405, 595, 785):
            cv2.line(image, (x, y), (x, y + 30), (200, 200, 200), 3)

    cv2.line(image, (0, STOP_Y), (W, STOP_Y), (255, 255, 255), 6)

    return image


class Vehicle:
    """One scripted vehicle. ``y(t)`` is its bottom edge in pixels."""

    def __init__(self, name, sprite, lane, cross_at=None, speed=108,
                 up=False, stop_at=None, parked_y=None, start=None,
                 klass=2):
        self.name, self.sprite, self.lane = name, sprite, lane
        self.speed, self.up, self.klass = speed, up, klass
        self.stop_at, self.parked_y = stop_at, parked_y
        height = sprite.shape[0]

        if parked_y is not None:
            self.first, self.last = 0.0, SECONDS
        elif up:
            self.first = start
            self.last = start + (H + height + 40) / speed
        else:
            # Appears at the top edge, crosses the stop line at ``cross_at``.
            self.first = cross_at - (STOP_Y - height) / speed
            self.cross_at = cross_at
            self.last = cross_at + (H + 40 - STOP_Y) / speed

    def y(self, t):
        if self.parked_y is not None:
            return self.parked_y

        if self.up:
            return H + 20 - self.speed * (t - self.first)

        bottom = STOP_Y + self.speed * (t - self.cross_at)

        if self.stop_at is not None:
            bottom = min(bottom, self.stop_at)

        return bottom

    def visible(self, t):
        return self.first <= t <= self.last and -50 < self.y(t) < H + 300


def build_vehicles():
    def sprite(name):
        boxes = json.loads((SAMPLES / "boxes.json").read_text())

        return cutout(SAMPLES / name, boxes.get(name))

    ordinary = [sprite(f"ordinary_{i}.jpg") for i in range(1, 7)]
    ambulance = sprite("ambulance_1.jpg")
    fire = sprite("fire_truck_1.jpg")
    police = sprite("police_car_1.jpg")

    return [
        # runs the red light (crosses at 2.5 s, signal is red until 6 s)
        Vehicle("red_light_runner", ordinary[0], LANES[0], cross_at=2.5),
        # crosses on green (8 s): no violation
        Vehicle("law_abiding", ordinary[1], LANES[1], cross_at=8.0),
        # speeding, on green: 10 m between the lines in 0.8 s = 45 km/h
        Vehicle("speeder", ordinary[2], LANES[2], cross_at=9.5, speed=270),
        # drives against the traffic (up the screen) during red
        Vehicle("wrong_way", ordinary[3], LANES[3], up=True, start=12.5,
                speed=150),
        # a stopped van, then a car that hits it and stops dead
        Vehicle("stopped_van", ordinary[4], LANES[4], parked_y=640),
        Vehicle("crasher", ordinary[5], LANES[4], cross_at=19.5, speed=230,
                stop_at=548),
        # emergency vehicles, one after another
        Vehicle("ambulance", ambulance, LANES[1], cross_at=15.5),
        Vehicle("fire_truck", fire, LANES[0], cross_at=22.0),
        Vehicle("police_car", police, LANES[2], cross_at=28.4),
    ]


def render(vehicles, writer=None):
    """Play the script. Returns per-frame ground-truth boxes."""

    base = road()
    truth = []

    for frame in range(FPS * SECONDS):
        t = frame / FPS
        canvas = base.copy()
        boxes = []

        for vehicle in sorted((v for v in vehicles if v.visible(t)),
                              key=lambda v: v.y(t)):
            box = paste(canvas, vehicle.sprite, vehicle.lane, vehicle.y(t))

            if box:
                boxes.append((vehicle, box))

        truth.append(boxes)

        if writer is not None:
            writer.write(canvas)

    return truth


class PerfectDetector:
    """Returns the scripted boxes (a detector that never makes a mistake)."""


    def __init__(self, truth):
        self.truth, self.frame = truth, 0

    def detect(self, image, conf=None):
        boxes = self.truth[min(self.frame, len(self.truth) - 1)]
        self.frame += 1

        return [{"class_id": v.klass, "class_name": "car", "confidence": 0.9,
                 "bbox": tuple(box)} for v, box in boxes
                ]


class PerfectTracker:
    """Keeps each scripted vehicle's identity."""

    def __init__(self, vehicles, truth):
        self.ids = {v.name: i + 1 for i, v in enumerate(vehicles)}
        self.truth, self.frame = truth, 0

    def update(self, detections):
        boxes = self.truth[min(self.frame, len(self.truth) - 1)]
        self.frame += 1

        return SimpleNamespace(
            xyxy=np.array([b for _, b in boxes], dtype=float).reshape(-1, 4),
            tracker_id=np.array([self.ids[v.name] for v, _ in boxes], int),
            class_id=np.array([v.klass for v, _ in boxes], int))


class PerfectEmergency:
    """Reports the scripted ambulance, fire truck and police car."""

    LABELS = {"ambulance": "ambulance", "fire_truck": "fire_truck",
              "police_car": "police_car"}

    def __init__(self, truth):
        self.truth, self.frame = truth, 0

    def detect(self, image, conf=None):
        boxes = self.truth[min(self.frame, len(self.truth) - 1)]
        self.frame += 1

        return [{"class_name": self.LABELS[v.name], "confidence": 0.9,
                 "bbox": tuple(box)} for v, box in boxes
                if v.name in self.LABELS]


def expected_events(video, vehicles, truth):
    """What the real checks report when detection is perfect."""

    import run_video

    out = ROOT / "outputs" / "demo_truth_run.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = run_video.main(
        ["--input", str(video), "--output", str(out), "--no-display",
         "--no-save", *SETTINGS],
        detector=PerfectDetector(truth),
        tracker=PerfectTracker(vehicles, truth),
        emergency_detector=PerfectEmergency(truth))

    rows = [(v["type"], v["time_seconds"]) for v in summary.violations]
    rows += [("collision", c["time_seconds"]) for c in summary.collisions]

    return sorted(rows, key=lambda r: r[1]), summary


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output", default=str(VIDEO))
    parser.add_argument("--no-truth", action="store_true",
                        help="only write the video")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    vehicles = build_vehicles()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"),
                             FPS, (W, H))

    if not writer.isOpened():
        print("This OpenCV build cannot write mp4v video.", file=sys.stderr)
        return 1

    truth = render(vehicles, writer)
    writer.release()
    print(f"Video written: {output}")

    if args.no_truth:
        return 0

    rows, summary = expected_events(output, vehicles, truth)

    with open(TRUTH, "w", newline="") as handle:
        csv.writer(handle).writerows([("type", "time_seconds"), *rows])

    print(f"\nWhat the checks report with perfect detection ({TRUTH.name}):")

    for kind, seconds in rows:
        print(f"  {seconds:6.2f} s  {kind}")

    for event in summary.emergency_events:
        print(f"  {event['time_seconds']:6.2f} s  emergency "
              f"({event['class_name']}), not scored")

    print("\nRun it with:\n  python scripts/run_video.py --input "
          f"{output.relative_to(ROOT)} " + " ".join(SETTINGS))

    return 0


if __name__ == "__main__":
    sys.exit(main())
