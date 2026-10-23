"""Turn your own traffic videos into pictures for training or testing.

    python scripts/extract_frames.py --video data/my_media/road.mp4 \
        --output data/negatives_own --every-seconds 2

Your own camera footage is the best material for teaching the emergency model
what *your* road looks like when nothing special is happening. Only use clips
with no emergency vehicle in them (you can also point this at a folder of
clips). Look through the pictures before training.
"""

import argparse
import sys
from pathlib import Path

VIDEO_TYPES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}


def extract(video, output, every_seconds=2.0, max_frames=None):
    """Save one picture every ``every_seconds``. Returns the file names."""

    import cv2

    video = Path(video)
    cap = cv2.VideoCapture(str(video))

    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps * every_seconds)))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    saved, number = [], 0

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                break

            if number % step == 0:
                name = f"{video.stem}_{number:06d}.jpg"
                cv2.imwrite(str(output / name), frame)
                saved.append(name)

                if max_frames and len(saved) >= max_frames:
                    break

            number += 1
    finally:
        cap.release()

    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--video", required=True,
                        help="a video file, or a folder of videos")
    parser.add_argument("--output", required=True)
    parser.add_argument("--every-seconds", type=float, default=2.0)
    parser.add_argument("--max-frames", type=int, default=None,
                        help="at most this many pictures per video")
    args = parser.parse_args(argv)
    source = Path(args.video)
    videos = (sorted(p for p in source.iterdir()
                     if p.suffix.lower() in VIDEO_TYPES)
              if source.is_dir() else [source])

    if not videos:
        print("No videos found.", file=sys.stderr)
        return 1

    total = 0

    for video in videos:
        try:
            names = extract(video, args.output, args.every_seconds,
                            args.max_frames)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            continue

        total += len(names)
        print(f"{video.name}: {len(names)} pictures")

    print(f"Saved {total} pictures to {args.output}. Check them by eye, and "
          "delete any that show an ambulance, fire truck or police car.")

    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
