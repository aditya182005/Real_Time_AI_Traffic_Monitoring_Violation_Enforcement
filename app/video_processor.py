import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2

from app import paths
from app.alerts import telegram_alert, twilio_alert
from app.annotate import (
    draw_trail,
    draw_zone,
    explain,
    EMERGENCY,
    VEHICLE,
    VIOLATION,
    crop_with_margin,
    draw_banner,
    draw_box,
)
from app import plates
from app.violation.collision_logic import CollisionHeuristic
from app.violation.zones import (
    CrossingMonitor,
    ParkingMonitor,
    RestrictedLane,
    TripleRiding,
)
from app.violation.helmet import HelmetChecker
from app.violation.red_light import RedLightDetector
from app.violation.signal import SignalSimulator
from app.violation.speed_estimator import SpeedEstimator
from app.violation.violation_logger import (
    log_collision_event,
    log_density_samples,
    log_vehicle_counts,
    log_priority_event,
    log_violation,
)
from app.violation.wrong_way import WrongWayDetector

ROOT = Path(__file__).resolve().parents[1]

VEHICLE_NAMES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck"
}

GREEN = (80, 200, 60)
RED = (60, 60, 240)
AMBER = (0, 170, 255)

ALERTS_OFF = "skipped (alerts off for this run)"


@dataclass
class SpeedConfig:
    """Two measurement lines (pixel rows) and the real distance between them."""

    line_a_y: int
    line_b_y: int
    distance_m: float
    limit_kmh: float
    x_min: int = None
    x_max: int = None


@dataclass
class WrongWayConfig:
    expected: str = "down"          # direction of normal traffic: down | up
    min_travel_px: int = 40
    x_min: int = None               # restrict to one carriageway (pixels)
    x_max: int = None


@dataclass
class VideoSummary:
    output_path: Path
    frames: int = 0
    total_frames: int = 0
    video_fps: float = 0.0
    processing_fps: float = 0.0
    duration_seconds: float = 0.0
    peak_vehicles: int = 0
    violations: list = field(default_factory=list)
    collisions: list = field(default_factory=list)
    density: list = field(default_factory=list)      # (second, avg vehicles)
    emergency_events: list = field(default_factory=list)
    signal_description: str = ""
    vehicle_counts: dict = field(default_factory=dict)   # class -> distinct vehicles

    def violations_of(self, kind):
        return [v for v in self.violations if v["type"] == kind]


def _open_writer(path, fps, size):
    # H.264 ("avc1") plays in browsers but is missing from many OpenCV
    # builds, so fall back to mp4v (the UI re-encodes it with ffmpeg).
    for code in ("avc1", "mp4v"):
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*code), fps, size
        )

        if writer.isOpened():
            return writer

        writer.release()

    return None


def _union_box(box_a, box_b):
    return (
        min(box_a[0], box_b[0]), min(box_a[1], box_b[1]),
        max(box_a[2], box_b[2]), max(box_a[3], box_b[3]),
    )


class TrafficVideoProcessor:

    def __init__(
        self,
        detector=None,
        tracker=None,
        stop_line_y=300,
        signal_state="RED",  # Simulated signal for testing
        signal=None,         # optional SignalSimulator (overrides signal_state)
        evidence_dir=None,
        emergency_detector=None,
        emergency_roi=None,  # (x1, y1, x2, y2); None = whole frame
        emergency_confirm_frames=3,
        priority_hold_seconds=10.0,
        speed=None,          # SpeedConfig, or None to skip speed checks
        wrong_way=None,      # WrongWayConfig, or None to skip
        helmet_detector=None,  # object with detect(frame) -> heads
        zones=None,          # ZoneConfig (parking, crossing, lane, triple)
        signal_output=None,  # object with send(state), e.g. an Arduino
        detect_collisions=False,
        send_collision_alerts=False,
        camera_id="CAM-01",
        alert_sender=None,   # test hook: callable(message) -> status string
        plate_reader=None,   # object with read(image) -> [(text, conf)]
        plate_locator=None,  # optional locator(crop) -> [(x1, y1, x2, y2)]
        plate_every=5,       # sample a vehicle's plate every N frames
        plate_min_height=60, # skip vehicles smaller than this (pixels)
    ):
        # Imported lazily so the heavy YOLO / supervision stack is only
        # loaded when real components are needed (tests inject fakes).
        if detector is None:
            from app.detection.detector import VehicleDetector
            detector = VehicleDetector()

        if tracker is None:
            from app.tracking.tracker import VehicleTracker
            tracker = VehicleTracker()

        self.detector = detector
        self.tracker = tracker
        self.stop_line_y = stop_line_y
        self.signal = signal or SignalSimulator.fixed(signal_state)
        self.signal_state = signal_state
        self.emergency_detector = emergency_detector
        self.emergency_roi = emergency_roi
        self.emergency_confirm_frames = emergency_confirm_frames
        self.priority_hold_seconds = priority_hold_seconds
        self.speed = speed
        self.wrong_way = wrong_way
        self.helmet_detector = helmet_detector
        self.zones = zones
        self.signal_output = signal_output
        self.detect_collisions = detect_collisions
        self.send_collision_alerts = send_collision_alerts
        self.camera_id = camera_id
        self.alert_sender = alert_sender
        self.plate_reader = plate_reader
        self.plate_locator = plate_locator
        self.plate_every = max(1, int(plate_every))
        self.plate_min_height = plate_min_height
        self.evidence_dir = (
            Path(evidence_dir)
            if evidence_dir
            else paths.OUTPUT_DIR / "violations"
        )

    def _normal_wait(self, tick, fps):
        """Seconds the ordinary signal would have kept this approach red.

        0 when it was already green, None when it cannot be known (a lamp
        read from the video, an adaptive signal, or one that never turns
        green). Used to report how much waiting the priority saved.
        """

        if not getattr(self.signal, "predictable", False):
            return None

        for step in range(0, 181):
            if self.signal.state_at(tick + int(step * fps), fps) == "GREEN":
                return float(step)

        return None

    def _in_roi(self, bbox):
        if self.emergency_roi is None:
            return True

        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rx1, ry1, rx2, ry2 = self.emergency_roi

        return rx1 <= cx <= rx2 and ry1 <= cy <= ry2

    def _read_plate(self, votes, track_id, image, bbox):
        """Read one vehicle's plate from ``image`` (a frame not yet drawn on)."""

        height, width = image.shape[:2]
        x1, y1 = max(0, bbox[0]), max(0, bbox[1])
        x2, y2 = min(width, bbox[2]), min(height, bbox[3])

        if y2 - y1 < self.plate_min_height or x2 <= x1:
            return

        try:
            result = plates.read_plate(
                self.plate_reader, image[y1:y2, x1:x2], self.plate_locator
            )
        except Exception as exc:  # OCR trouble must never stop the analysis
            print(f"Plate reading failed: {type(exc).__name__}: {exc}")
            return

        votes.add(track_id, result)

    def process(
        self,
        input_path,
        output_path,
        show=True,
        progress=None,
        source=None,
        save_to_db=True,
        max_frames=None,
        run_id=None,
        frame_callback=None,
        preview_every=4,
        capture=None,
        live=False,
        stop_event=None,
        max_seconds=None,
        on_event=None,
    ):
        """Run the pipeline over a video and return a ``VideoSummary``.

        progress:       optional ``callback(frame_number, total_frames)``.
        frame_callback: optional ``callback(annotated_frame, frame_number)``
                        called every ``preview_every`` frames (live preview).
                        The frame must be treated as read-only.
        source:         label stored with database records (e.g. file name).
        save_to_db:     log events / density to SQLite.
        max_frames:     stop early after this many frames (long uploads).
        run_id:         makes event keys and evidence names unique per run.
        capture:        an already-open source with the ``cv2.VideoCapture``
                        methods (see app/live.py); replaces ``input_path``.
        live:           the source never ends. Time comes from the wall
                        clock (frames may be dropped), no video file is
                        written when ``output_path`` is None, and an empty
                        read means "wait for the next frame".
        stop_event:     a ``threading.Event``; the run ends when it is set.
        max_seconds:    stop after this much real time (live runs).
        on_event:       optional ``callback(kind, entry)`` for each violation
                        ("violation") and collision ("collision").
        """

        cap = capture if capture is not None else cv2.VideoCapture(
            str(input_path))

        if not cap.isOpened():
            raise ValueError(f"Could not open video: {input_path}")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        if not fps or fps <= 0:
            fps = 30

        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        out = None

        if output_path is not None:
            # VideoWriter fails silently when the folder is missing.
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            out = _open_writer(output_path, fps, (width, height))

            if out is None:
                cap.release()
                raise ValueError(
                    f"Could not open output video: {output_path}")

        # Fresh detector state for every run.
        red_light = RedLightDetector(self.stop_line_y)
        speed_estimator = (
            SpeedEstimator(
                self.speed.line_a_y, self.speed.line_b_y,
                self.speed.distance_m, self.speed.x_min, self.speed.x_max,
            ) if self.speed else None
        )
        helmet_checker = (
            HelmetChecker() if self.helmet_detector is not None else None)
        wrong_way_detector = (
            WrongWayDetector(
                self.wrong_way.expected, self.wrong_way.min_travel_px,
                x_min=self.wrong_way.x_min, x_max=self.wrong_way.x_max,
            ) if self.wrong_way else None
        )
        collision_heuristic = (
            CollisionHeuristic() if self.detect_collisions else None
        )
        zones = self.zones if (self.zones and self.zones.active) else None
        parking = (
            ParkingMonitor(zones.no_parking["polygon"],
                           zones.no_parking["seconds"])
            if zones and zones.no_parking else None)
        crossing = (
            CrossingMonitor(zones.crossing["y_top"], zones.crossing["y_bottom"])
            if zones and zones.crossing else None)
        lane_rule = (
            RestrictedLane(zones.restricted_lane["polygon"],
                           zones.restricted_lane["allowed"])
            if zones and zones.restricted_lane else None)
        triple = (
            TripleRiding()
            if zones and zones.triple_riding
            and self.helmet_detector is not None else None)
        trails = {}             # track_id -> recent (x, y) positions
        seen_ids = {}           # track_id -> class (for the class counts)
        plate_votes = (
            plates.PlateVotes() if self.plate_reader is not None else None
        )

        name_part = run_id or "run"
        key_part = f"{run_id}:" if run_id else ""
        hold_frames = int(self.priority_hold_seconds * fps)

        summary = VideoSummary(
            output_path=output_path,
            total_frames=total_frames,
            video_fps=fps,
            signal_description=self.signal.describe(),
        )

        density = {}            # video second -> list of vehicle counts
        emergency_streak = 0
        emergency_logged = False
        override_until = 0      # last frame the emergency override covers
        alert_threads = []
        frame_number = 0
        tick = 0                # the time axis, in frames (see below)
        started = time.perf_counter()

        try:
            while True:

                if max_frames and frame_number >= max_frames:
                    break

                if stop_event is not None and stop_event.is_set():
                    break

                if max_seconds and (
                    time.perf_counter() - started >= max_seconds
                ):
                    break

                ret, frame = cap.read()

                if not ret:
                    # A live source returning nothing is usually just "no
                    # new frame yet"; it ends only when it says it is done.
                    if live and not getattr(cap, "finished", True):
                        continue

                    break

                frame_number += 1

                # Every time-based check (speed, signal cycle, emergency
                # hold, density) runs on ``tick``. For a file it is the
                # frame number. For a live stream it follows the wall clock,
                # because frames may have been dropped.
                if live:
                    tick = max(
                        tick + 1,
                        int((time.perf_counter() - started) * fps) + 1,
                    )
                else:
                    tick = frame_number

                seconds = round((tick - 1) / fps, 2)

                detections = self.detector.detect(frame)
                tracked = self.tracker.update(detections)

                # -- emergency vehicles and the simulated signal override ----
                emergencies = []

                if self.emergency_detector is not None:
                    emergencies = [
                        e for e in self.emergency_detector.detect(frame)
                        if self._in_roi(e["bbox"])
                    ]

                # Confirm over several frames so one noisy detection does
                # not flip the signal.
                emergency_streak = emergency_streak + 1 if emergencies else 0
                priority_active = (
                    emergency_streak >= self.emergency_confirm_frames
                )

                if priority_active:
                    override_until = tick + hold_frames

                    if not emergency_logged:
                        emergency_logged = True
                        best = max(emergencies, key=lambda e: e["confidence"])
                        wait = self._normal_wait(tick, fps)
                        summary.emergency_events.append({
                            "normal_wait_seconds": wait,
                            "frame": frame_number,
                            "time_seconds": seconds,
                            "class_name": best["class_name"],
                            "confidence": round(best["confidence"], 3),
                            "signal_override": True,
                        })

                        if save_to_db:
                            log_priority_event(
                                best["class_name"], best["confidence"],
                                camera_id=self.camera_id, source=source,
                                normal_wait_seconds=wait,
                            )

                elif not emergencies:
                    emergency_logged = False

                observe_queue = getattr(self.signal, "observe_queue", None)

                if observe_queue is not None:
                    # Vehicles waiting just before the stop line (the
                    # adaptive signal sizes the next green from this).
                    depth = 0.4 * frame.shape[0]
                    observe_queue(sum(
                        1 for box in tracked.xyxy
                        if self.stop_line_y - depth <= box[3] <= self.stop_line_y
                    ))

                observe = getattr(self.signal, "observe", None)

                if observe is not None:   # a lamp reader needs the picture
                    observe(frame)

                override = tick <= override_until
                signal_state = (
                    "GREEN" if override
                    else self.signal.state_at(tick, fps)
                )

                heads = []

                if helmet_checker is not None or triple is not None:
                    try:
                        heads = self.helmet_detector.detect(frame)
                    except Exception as exc:  # never stop the analysis
                        print(f"Helmet check failed: {type(exc).__name__}")

                if self.signal_output is not None:
                    try:
                        self.signal_output.send(signal_state)
                    except Exception as exc:  # a loose cable must not stop us
                        print(f"Signal output stopped: {exc}")
                        self.signal_output = None

                # -- per-vehicle checks --------------------------------------
                vehicles = []
                events = []     # (type, track_id, bbox, class_name, extra)

                for i in range(len(tracked.xyxy)):
                    bbox = tuple(map(int, tracked.xyxy[i]))
                    center_x = (bbox[0] + bbox[2]) / 2

                    track_id = (
                        int(tracked.tracker_id[i])
                        if tracked.tracker_id is not None
                        else -1
                    )

                    class_name = VEHICLE_NAMES.get(
                        int(tracked.class_id[i]), "vehicle"
                    )

                    flagged = False

                    if track_id != -1:
                        if red_light.check(track_id, bbox[3], signal_state):
                            events.append(
                                ("red_light", track_id, bbox, class_name, {})
                            )
                            flagged = True

                        if speed_estimator is not None:
                            kmh = speed_estimator.update(
                                track_id, center_x, bbox[3], tick, fps
                            )

                            if kmh is not None and kmh > self.speed.limit_kmh:
                                events.append((
                                    "speeding", track_id, bbox, class_name,
                                    {"speed_kmh": round(kmh, 1)},
                                ))
                                flagged = True

                        if wrong_way_detector is not None and (
                            wrong_way_detector.update(
                                track_id, center_x, bbox[3]
                            )
                        ):
                            events.append(
                                ("wrong_way", track_id, bbox, class_name, {})
                            )
                            flagged = True

                    if (
                        helmet_checker is not None and track_id != -1
                        and class_name == "motorcycle"
                        and helmet_checker.update(track_id, bbox, heads)
                    ):
                        events.append(
                            ("no_helmet", track_id, bbox, class_name, {})
                        )
                        flagged = True

                    if track_id != -1:
                        seen_ids.setdefault(track_id, class_name)
                        trail = trails.setdefault(track_id, [])
                        trail.append((center_x, bbox[3]))
                        del trail[:-40]

                        checks = []

                        if parking is not None:
                            checks.append((
                                "illegal_parking",
                                parking.update(track_id, bbox, seconds)))

                        if crossing is not None:
                            checks.append((
                                "crossing_encroachment",
                                crossing.update(
                                    track_id, bbox, signal_state, seconds)))

                        if lane_rule is not None:
                            checks.append((
                                "wrong_lane",
                                lane_rule.update(track_id, bbox, class_name)))

                        if triple is not None and class_name == "motorcycle":
                            checks.append((
                                "triple_riding",
                                triple.update(track_id, bbox, heads)))

                        for kind_name, hit in checks:
                            if hit:
                                events.append((kind_name, track_id, bbox,
                                               class_name, {}))
                                flagged = True

                    if (
                        plate_votes is not None and track_id != -1
                        and frame_number % self.plate_every == 0
                        and plate_votes.wants_more(track_id)
                    ):
                        self._read_plate(plate_votes, track_id, frame, bbox)

                    measured = (
                        speed_estimator.speeds.get(track_id)
                        if speed_estimator is not None else None
                    )
                    vehicles.append(
                        (track_id, bbox, class_name, flagged, measured)
                    )

                collisions = []

                if collision_heuristic is not None:
                    collisions = collision_heuristic.update(
                        [(v[0], v[1]) for v in vehicles if v[0] != -1]
                    )

                # A clean copy for the evidence crops, taken before drawing.
                clean = frame.copy() if (events or collisions) else None

                # -- drawing -------------------------------------------------
                collided = {t for pair, _, _ in collisions for t in pair}

                for track_id, bbox, class_name, flagged, measured in vehicles:
                    label = f"{class_name} ID:{track_id}"

                    if measured is not None:
                        label += f" {measured:.0f} km/h"

                    draw_box(
                        frame, bbox, label,
                        VIOLATION if (flagged or track_id in collided)
                        else VEHICLE,
                    )

                for emergency in emergencies:
                    draw_box(
                        frame,
                        emergency["bbox"],
                        f"{emergency['class_name']} "
                        f"{emergency['confidence']:.2f}",
                        EMERGENCY,
                        thickness=3,
                    )

                width_now = frame.shape[1]
                line_colour = RED if signal_state == "RED" else GREEN

                cv2.line(frame, (0, self.stop_line_y),
                         (width_now, self.stop_line_y), line_colour, 2)

                if zones is not None:
                    if zones.no_parking:
                        draw_zone(frame, zones.no_parking["polygon"], AMBER,
                                  "No parking")

                    if zones.restricted_lane:
                        draw_zone(frame, zones.restricted_lane["polygon"],
                                  VIOLATION, "Restricted lane")

                    if zones.crossing:
                        cv2.rectangle(
                            frame, (0, int(zones.crossing["y_top"])),
                            (width_now, int(zones.crossing["y_bottom"])),
                            AMBER, 1)

                if self.speed is not None:
                    for line_y in (self.speed.line_a_y, self.speed.line_b_y):
                        cv2.line(frame, (0, line_y), (width_now, line_y),
                                 AMBER, 1)

                signal_label = getattr(self.signal, "label", "simulated")
                banner = f"Signal: {signal_state} ({signal_label})"

                if override:
                    banner = "Signal: GREEN (emergency override, simulated)"

                next_y = draw_banner(frame, banner, line_colour)

                if priority_active:
                    next_y = draw_banner(
                        frame, "PRIORITY REQUEST (SIMULATED)", EMERGENCY,
                        origin=(15, next_y),
                    )

                for pair, box_a, box_b in collisions:
                    draw_banner(
                        frame, "POSSIBLE COLLISION - VERIFY", VIOLATION,
                        origin=(15, next_y),
                    )
                    next_y += 40

                # -- save evidence AFTER drawing, then log once --------------
                for kind, track_id, bbox, class_name, extra in events:
                    plate = None

                    if plate_votes is not None and track_id != -1:
                        if plate_votes.best(track_id) is None:
                            # Nothing read yet: try once on the clean frame.
                            self._read_plate(
                                plate_votes, track_id, clean, bbox)

                        plate = plate_votes.best(track_id)

                    # Say why on the picture, so a reviewer can check it.
                    evidence_frame = frame.copy()
                    draw_trail(evidence_frame, trails.get(track_id, []))
                    draw_banner(
                        evidence_frame,
                        explain(kind, signal_state, extra.get("speed_kmh")),
                        VIOLATION, origin=(15, frame.shape[0] - 55),
                    )

                    stem = (
                        f"{name_part}_{kind}_id_{track_id}"
                        f"_frame_{frame_number}"
                    )
                    evidence_path = self.evidence_dir / f"{stem}.jpg"
                    crop_path = self.evidence_dir / f"{stem}_crop.jpg"

                    cv2.imwrite(str(evidence_path), evidence_frame)
                    cv2.imwrite(str(crop_path), crop_with_margin(clean, bbox))

                    inserted = None

                    if save_to_db:
                        inserted = log_violation(
                            event_key=(
                                f"{kind}:{key_part}{track_id}:{frame_number}"
                            ),
                            track_id=track_id,
                            violation_type=kind,
                            evidence_path=evidence_path,
                            speed=extra.get("speed_kmh"),
                            speed_limit=(
                                self.speed.limit_kmh
                                if kind == "speeding" else None
                            ),
                            signal_state=(
                                signal_state if kind == "red_light" else None
                            ),
                            source=source,
                            crop_path=crop_path,
                            camera_id=self.camera_id,
                            plate_text=plate[0] if plate else None,
                            plate_confidence=plate[1] if plate else None,
                            position=(
                                round(((bbox[0] + bbox[2]) / 2) / width, 3),
                                round(bbox[3] / height, 3),
                            ),
                        )

                    entry = {
                        "type": kind,
                        "track_id": track_id,
                        "vehicle": class_name,
                        "frame": frame_number,
                        "time_seconds": seconds,
                        "signal_state": (
                            signal_state if kind == "red_light" else None
                        ),
                        "speed_kmh": extra.get("speed_kmh"),
                        "evidence_path": str(evidence_path),
                        "crop_path": str(crop_path),
                        "plate_text": plate[0] if plate else None,
                        "plate_confidence": plate[1] if plate else None,
                    }
                    summary.violations.append(entry)

                    if on_event:
                        on_event("violation", entry)

                    print(
                        f"{kind} detected: ID {track_id} "
                        f"(record inserted: {inserted})"
                    )

                for pair, box_a, box_b in collisions:
                    id_a, id_b = pair
                    stem = (
                        f"{name_part}_collision_{id_a}_{id_b}"
                        f"_frame_{frame_number}"
                    )
                    evidence_path = self.evidence_dir / f"{stem}.jpg"
                    crop_path = self.evidence_dir / f"{stem}_crop.jpg"

                    cv2.imwrite(str(evidence_path), frame)
                    cv2.imwrite(
                        str(crop_path),
                        crop_with_margin(clean, _union_box(box_a, box_b)),
                    )

                    stamp = datetime.now(timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S UTC"
                    )
                    message = (
                        f"Traffic Agent [{self.camera_id}] {stamp}: possible "
                        f"collision between vehicle tracks {id_a} and {id_b} "
                        f"at {seconds}s of {source or 'the video'}. "
                        f"Please verify the incident."
                    )

                    status = (
                        "pending" if self.send_collision_alerts
                        else ALERTS_OFF
                    )

                    entry = {
                        "track_ids": (id_a, id_b),
                        "frame": frame_number,
                        "time_seconds": seconds,
                        "evidence_path": str(evidence_path),
                        "crop_path": str(crop_path),
                        "alert_status": status,
                    }

                    if save_to_db:
                        event_id = log_collision_event(
                            id_a, id_b, evidence_path,
                            camera_id=self.camera_id, source=source,
                            crop_path=crop_path, alert_status=status,
                        )

                        if self.send_collision_alerts:
                            # Runs off this thread; the outcome is written
                            # back to the collision record and this entry.
                            options = {
                                "on_done": (
                                    lambda result, e=entry:
                                    e.update(alert_status=result)
                                ),
                            }

                            if self.alert_sender:
                                options["sender"] = self.alert_sender

                            alert_threads.append(
                                twilio_alert.dispatch(
                                    event_id, message, **options
                                )
                            )
                    elif self.send_collision_alerts:
                        entry["alert_status"] = "skipped (results not saved)"

                    if self.send_collision_alerts and telegram_alert.is_configured():
                        # Second channel; the Twilio status stays the record.
                        entry["telegram_status"] = "pending"
                        alert_threads.append(telegram_alert.notify(
                            message, photo=evidence_path,
                            on_done=lambda r, e=entry:
                            e.update(telegram_status=r)))

                    summary.collisions.append(entry)

                    if on_event:
                        on_event("collision", entry)

                    print(message)

                count = len(vehicles)
                summary.peak_vehicles = max(summary.peak_vehicles, count)
                density.setdefault(int((tick - 1) / fps), []).append(
                    count
                )

                if out is not None:
                    out.write(frame)

                if frame_callback and (frame_number % preview_every == 0):
                    frame_callback(frame, frame_number)

                if progress and (frame_number % 5 == 0):
                    progress(frame_number, total_frames)

                if show:
                    cv2.imshow("Traffic Agent", frame)

                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

        finally:
            cap.release()

            if out is not None:
                out.release()

            if show:
                cv2.destroyAllWindows()

        # Let alerts already in flight finish (bounded, in case Twilio hangs).
        for thread in alert_threads:
            if thread is not None:
                thread.join(timeout=30)

        elapsed = max(time.perf_counter() - started, 1e-9)

        summary.frames = frame_number
        summary.processing_fps = frame_number / elapsed
        summary.duration_seconds = frame_number / fps
        summary.vehicle_counts = dict(Counter(seen_ids.values()))
        summary.density = [
            (second, sum(counts) / len(counts))
            for second, counts in sorted(density.items())
        ]

        if save_to_db:
            log_density_samples(
                source or "video", summary.density, camera_id=self.camera_id
            )
            log_vehicle_counts(
                source or "video", summary.vehicle_counts,
                camera_id=self.camera_id)

        if progress:
            progress(frame_number, total_frames)

        return summary
