import argparse

from app.video_processor import TrafficVideoProcessor


parser = argparse.ArgumentParser(
    description="Detect, track and flag red-light crossings in a video."
)
parser.add_argument("--input", default="data/videos/traffic.mp4")
parser.add_argument(
    "--output", default="outputs/detections/tracked_traffic.mp4"
)
parser.add_argument(
    "--stop-line-y", type=int, default=300,
    help="Pixel row of the stop line (depends on your video)."
)
parser.add_argument(
    "--signal", choices=["RED", "GREEN"], default="RED",
    help="Simulated signal state for the whole run."
)
parser.add_argument(
    "--no-display", action="store_true",
    help="Do not open a preview window (for servers / headless runs)."
)
args = parser.parse_args()

processor = TrafficVideoProcessor(
    stop_line_y=args.stop_line_y,
    signal_state=args.signal,
)

processor.process(
    args.input,
    args.output,
    show=not args.no_display,
)

print("Video processing completed.")
