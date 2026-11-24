"""Click four points on the road to calibrate real distances for speed checks.

    python scripts/calibrate_speed.py --input clip.mp4 --width-m 3.5 --length-m 12

A window shows the first frame. Click the four corners of a rectangle on the
road whose real size you know, in this order: near-left, near-right,
far-right, far-left. Press Enter to save, R to start again, Q to quit.
Then run the video with ``--calibration outputs/calibration.json``.

No window (a server)? Give the points yourself:

    --points "120,640;520,640;430,300;210,300"
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.calibration import Calibration, CalibrationError  # noqa: E402


def parse_points(text):
    try:
        points = [tuple(float(v) for v in pair.split(","))
                  for pair in text.split(";")]
    except ValueError as exc:
        raise CalibrationError(
            'Points look like "x,y;x,y;x,y;x,y".') from exc

    if len(points) != 4 or any(len(p) != 2 for p in points):
        raise CalibrationError("Give exactly four x,y points.")

    return points


def pick_points(frame):
    import cv2

    points = []
    window = "Click 4 corners: near-left, near-right, far-right, far-left"

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x, y))

    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_click)

    while True:
        view = frame.copy()

        for i, (x, y) in enumerate(points):
            cv2.circle(view, (x, y), 6, (0, 215, 255), -1)
            cv2.putText(view, str(i + 1), (x + 8, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 215, 255), 2)

        cv2.imshow(window, view)
        key = cv2.waitKey(30) & 0xFF

        if key in (ord("q"), 27):
            cv2.destroyAllWindows()
            raise SystemExit("Cancelled.")

        if key in (ord("r"), ord("R")):
            points.clear()

        if key in (13, 10) and len(points) == 4:
            cv2.destroyAllWindows()
            return points


def first_frame(path):
    import cv2

    cap = cv2.VideoCapture(str(path))
    ok, frame = cap.read()
    cap.release()

    if not ok:
        image = cv2.imread(str(path))

        if image is None:
            raise SystemExit(f"Could not read a picture from {path}.")

        return image

    return frame


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="video or image to click on")
    parser.add_argument("--width-m", type=float, required=True)
    parser.add_argument("--length-m", type=float, required=True)
    parser.add_argument("--points", help='"x,y;x,y;x,y;x,y" instead of clicking')
    parser.add_argument("--output", default=str(ROOT / "outputs" / "calibration.json"))
    parser.add_argument("--rows", metavar="A,B",
                        help="also print the distance between these pixel rows")
    args = parser.parse_args(argv)

    try:
        if args.points:
            points = parse_points(args.points)
        elif args.input:
            points = pick_points(first_frame(args.input))
        else:
            parser.error("give --input to click on, or --points")

        calibration = Calibration(points, args.width_m, args.length_m)
    except CalibrationError as exc:
        raise SystemExit(f"Calibration failed: {exc}")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    calibration.save(args.output)
    print(f"Saved {args.output}")

    if args.rows:
        a, b = (float(v) for v in args.rows.split(","))
        print(f"Distance between rows {a:g} and {b:g}: "
              f"{calibration.distance_between_rows(a, b):.2f} m")

    return calibration


if __name__ == "__main__":
    main()
