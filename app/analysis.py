"""Analysis of single uploaded images (the video path is in video_processor)."""

import time
from collections import Counter
from dataclasses import dataclass, field

from app.annotate import EMERGENCY, VEHICLE, draw_banner, draw_box
from app.violation.signal import SignalSimulator


@dataclass
class ImageReport:
    annotated: object                 # BGR ndarray with boxes drawn
    vehicles: list = field(default_factory=list)
    emergencies: list = field(default_factory=list)
    seconds: float = 0.0

    @property
    def counts(self):
        return dict(Counter(v["class_name"] for v in self.vehicles))

    @property
    def priority_requested(self):
        return bool(self.emergencies)


def analyze_image(image, detector, emergency_detector=None,
                  conf=None, emergency_conf=None):
    """Detect vehicles (and emergency vehicles) in one BGR image."""

    started = time.perf_counter()

    vehicles = detector.detect(image, conf=conf)
    emergencies = (
        emergency_detector.detect(image, conf=emergency_conf)
        if emergency_detector is not None
        else []
    )

    annotated = image.copy()

    for vehicle in vehicles:
        draw_box(
            annotated,
            vehicle["bbox"],
            f"{vehicle['class_name']} {vehicle['confidence']:.2f}",
            VEHICLE,
        )

    for emergency in emergencies:
        draw_box(
            annotated,
            emergency["bbox"],
            f"{emergency['class_name']} {emergency['confidence']:.2f}",
            EMERGENCY,
            thickness=3,
        )

    if emergencies:
        draw_banner(
            annotated, "PRIORITY REQUEST (SIMULATED)", EMERGENCY
        )

    return ImageReport(
        annotated=annotated,
        vehicles=vehicles,
        emergencies=emergencies,
        seconds=time.perf_counter() - started,
    )


# -- video settings -----------------------------------------------------------

@dataclass
class VideoSettings:
    """Everything the user can tune for a video run.

    Positions are percentages of the frame (so they survive any resolution)
    and are converted to pixels by ``build_processor``.
    """

    camera_id: str = "CAM-01"
    stop_line_pct: float = 60
    signal_mode: str = "red"            # red | green | cycle
    red_seconds: float = 10
    green_seconds: float = 10

    check_speed: bool = False
    speed_line_a_pct: float = 45
    speed_line_b_pct: float = 75
    speed_distance_m: float = 10
    speed_limit_kmh: float = 40

    check_wrong_way: bool = False
    expected_direction: str = "down"    # down | up
    lane_from_pct: float = 0
    lane_to_pct: float = 100

    check_collisions: bool = False
    send_alerts: bool = False

    use_emergency: bool = False
    save_to_db: bool = True


def pixel_row(height, pct):
    return int(round(height * pct / 100.0))


def pixel_col(width, pct):
    return int(round(width * pct / 100.0))


def validate_settings(settings):
    """Return a list of plain-language problems (empty when fine)."""

    problems = []

    if settings.check_speed:
        if settings.speed_line_a_pct == settings.speed_line_b_pct:
            problems.append("Move speed line A and B apart.")

        if settings.speed_distance_m <= 0:
            problems.append("Enter the real distance between the speed lines.")

    if settings.check_wrong_way and (
        settings.lane_from_pct >= settings.lane_to_pct
    ):
        problems.append("The lane range must have some width.")

    if settings.signal_mode == "cycle" and (
        settings.red_seconds <= 0 or settings.green_seconds <= 0
    ):
        problems.append("Signal times must be above zero.")

    return problems


def build_signal(settings):
    if settings.signal_mode == "green":
        return SignalSimulator.fixed("GREEN")

    if settings.signal_mode == "cycle":
        return SignalSimulator.cycle(
            float(settings.red_seconds), float(settings.green_seconds)
        )

    return SignalSimulator.fixed("RED")


def build_processor(settings, width, height, detector, tracker,
                    emergency_detector, evidence_dir):
    """Create a configured ``TrafficVideoProcessor`` for a video's size."""

    from app.video_processor import (
        SpeedConfig,
        TrafficVideoProcessor,
        WrongWayConfig,
    )

    lane_from = pixel_col(width, settings.lane_from_pct)
    lane_to = pixel_col(width, settings.lane_to_pct)

    speed = None

    if settings.check_speed:
        speed = SpeedConfig(
            line_a_y=pixel_row(height, settings.speed_line_a_pct),
            line_b_y=pixel_row(height, settings.speed_line_b_pct),
            distance_m=float(settings.speed_distance_m),
            limit_kmh=float(settings.speed_limit_kmh),
        )

    wrong_way = None

    if settings.check_wrong_way:
        wrong_way = WrongWayConfig(
            expected=settings.expected_direction,
            x_min=lane_from,
            x_max=lane_to,
        )

    return TrafficVideoProcessor(
        detector=detector,
        tracker=tracker,
        stop_line_y=pixel_row(height, settings.stop_line_pct),
        signal=build_signal(settings),
        evidence_dir=evidence_dir,
        emergency_detector=(
            emergency_detector if settings.use_emergency else None
        ),
        speed=speed,
        wrong_way=wrong_way,
        detect_collisions=settings.check_collisions,
        send_collision_alerts=(
            settings.check_collisions and settings.send_alerts
        ),
        camera_id=settings.camera_id.strip() or "CAM-01",
    )
