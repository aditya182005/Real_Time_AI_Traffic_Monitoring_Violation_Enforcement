"""Run the whole pipeline on a video from the command line.

Examples (from the project root):

    python run_video.py --no-display
    python run_video.py --speed --distance-m 12 --speed-limit 50 --collisions
    python run_video.py --input clip.mp4 --signal cycle --wrong-way --no-save

This uses the same settings and code as the "Analyze footage" page of the
dashboard, so results match.
"""

import argparse
import os
import uuid
from pathlib import Path

import cv2

from app.analysis import VideoSettings, build_processor, validate_settings

ROOT = Path(__file__).resolve().parent


def build_parser():
    parser = argparse.ArgumentParser(
        description="Detect, track and check vehicles in a video "
                    "(red light, speed, wrong way, collisions, emergency)."
    )

    parser.add_argument("--input", default="data/videos/traffic.mp4")
    parser.add_argument(
        "--output", default="outputs/detections/tracked_traffic.mp4"
    )
    parser.add_argument(
        "--camera-id", default=os.getenv("CAMERA_ID", "CAM-01"),
        help="Name stored with every record (default: $CAMERA_ID or CAM-01)."
    )

    signal = parser.add_argument_group("stop line and simulated signal")
    signal.add_argument(
        "--stop-line-pct", type=float, default=60,
        help="Stop line position, percent from the top of the frame."
    )
    signal.add_argument(
        "--signal", type=str.lower, choices=["red", "green", "cycle"],
        default="red", help="Simulated signal for the whole run."
    )
    signal.add_argument("--red-seconds", type=float, default=10)
    signal.add_argument("--green-seconds", type=float, default=10)

    speed = parser.add_argument_group("speed check")
    speed.add_argument("--speed", action="store_true",
                       help="Measure speed between two lines.")
    speed.add_argument("--line-a-pct", type=float, default=45)
    speed.add_argument("--line-b-pct", type=float, default=75)
    speed.add_argument("--distance-m", type=float, default=10,
                       help="Real distance between the two lines, in metres.")
    speed.add_argument("--speed-limit", type=float, default=40,
                       help="Speed limit in km/h.")

    wrong = parser.add_argument_group("wrong-way check")
    wrong.add_argument("--wrong-way", action="store_true")
    wrong.add_argument("--direction", choices=["down", "up"], default="down",
                       help="Direction normal traffic moves in the image.")
    wrong.add_argument("--lane-from-pct", type=float, default=0)
    wrong.add_argument("--lane-to-pct", type=float, default=100)

    other = parser.add_argument_group("other checks")
    other.add_argument("--collisions", action="store_true",
                       help="Look for possible collisions.")
    other.add_argument(
        "--send-alerts", action="store_true",
        help="Send a Twilio SMS for each collision (needs a .env file)."
    )
    other.add_argument(
        "--emergency", action="store_true",
        help="Turn the simulated signal green for emergency vehicles "
             "(needs models/emergency_vehicle.pt)."
    )

    run = parser.add_argument_group("run options")
    run.add_argument("--max-frames", type=int, default=None)
    run.add_argument("--no-save", action="store_true",
                     help="Do not write results to the database.")
    run.add_argument("--no-display", action="store_true",
                     help="Do not open a preview window (servers, SSH).")

    return parser


def settings_from_args(args):
    return VideoSettings(
        camera_id=args.camera_id,
        stop_line_pct=args.stop_line_pct,
        signal_mode=args.signal,
        red_seconds=args.red_seconds,
        green_seconds=args.green_seconds,
        check_speed=args.speed,
        speed_line_a_pct=args.line_a_pct,
        speed_line_b_pct=args.line_b_pct,
        speed_distance_m=args.distance_m,
        speed_limit_kmh=args.speed_limit,
        check_wrong_way=args.wrong_way,
        expected_direction=args.direction,
        lane_from_pct=args.lane_from_pct,
        lane_to_pct=args.lane_to_pct,
        check_collisions=args.collisions,
        send_alerts=args.send_alerts,
        use_emergency=args.emergency,
        save_to_db=not args.no_save,
    )


def video_size(path):
    cap = cv2.VideoCapture(str(path))

    try:
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {path}")

        return (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
    finally:
        cap.release()


def main(argv=None, detector=None, tracker=None, emergency_detector=None):
    """``detector``/``tracker``/``emergency_detector`` are for tests."""

    parser = build_parser()
    args = parser.parse_args(argv)
    settings = settings_from_args(args)

    problems = validate_settings(settings)

    if problems:
        parser.error(" ".join(problems))

    if args.send_alerts and not args.collisions:
        parser.error("--send-alerts needs --collisions.")

    width, height = video_size(args.input)

    if detector is None:
        from app.detection.detector import VehicleDetector

        detector = VehicleDetector()

    if tracker is None:
        from app.tracking.tracker import VehicleTracker

        tracker = VehicleTracker()

    if args.emergency and emergency_detector is None:
        from app.detection.emergency_detector import EmergencyDetector

        if not EmergencyDetector.available():
            parser.error(
                "--emergency needs models/emergency_vehicle.pt "
                "(see the README: Training the emergency-vehicle model)."
            )

        emergency_detector = EmergencyDetector()

    # A fresh run ID keeps event keys unique: track IDs and frame numbers
    # repeat between runs, and a repeated key is silently ignored.
    run_id = uuid.uuid4().hex[:8]

    processor = build_processor(
        settings, width, height, detector, tracker, emergency_detector,
        ROOT / "outputs" / "violations" / run_id,
    )

    summary = processor.process(
        args.input,
        args.output,
        show=not args.no_display,
        source=Path(args.input).name,
        save_to_db=settings.save_to_db,
        max_frames=args.max_frames,
        run_id=run_id,
    )

    print(
        f"\nDone: {summary.frames} frames in "
        f"{summary.duration_seconds:.1f}s of video "
        f"({summary.processing_fps:.1f} FPS)."
    )
    print(
        f"Violations: {len(summary.violations)}  "
        f"Possible collisions: {len(summary.collisions)}  "
        f"Emergency vehicles: {len(summary.emergency_events)}"
    )
    print(f"Annotated video: {summary.output_path}")

    if settings.save_to_db:
        print("Results saved. Open the dashboard: streamlit run app/main.py")

    return summary


if __name__ == "__main__":
    main()
