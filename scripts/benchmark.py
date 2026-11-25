"""Measure precision and recall of each violation type on your own clips.

1. Put clips in a folder (``clips/``).
2. Write what really happens in them, by watching, in a CSV
   (``clips/truth.csv``)::

       clip,type,time_seconds
       junction1.mp4,red_light,12.4
       junction1.mp4,speeding,31.0
       junction2.mp4,wrong_way,5.2

   A clip with no row is a clip where nothing should be flagged.
3. Run (options after ``--`` go to run_video.py, so use the same ones you
   would for a real run)::

       python scripts/benchmark.py --clips clips --truth clips/truth.csv \\
           -- --signal cycle --speed --distance-m 12 --wrong-way

A detection counts as correct (TP) when the same clip has a truth row of the
same type within ``--tolerance`` seconds (default 3). Truth rows nobody
matched are misses (FN); detections matching nothing are false alarms (FP).
Each truth row is used once. The report gives precision, recall, F1 and a 95%
Wilson interval, which shows how little a small sample proves: 8 of 8 found
still leaves recall anywhere from about 68% to 100%.

Written to outputs/benchmark.md and .json.
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}


class TruthError(ValueError):
    """The truth file is missing or has a bad row."""


def read_truth(path):
    """List of ``(clip, type, seconds)`` from a CSV file."""

    try:
        handle = open(path, newline="", encoding="utf-8")
    except OSError as exc:
        raise TruthError(f"Cannot read {path}: {exc}") from exc

    rows = []

    with handle:
        reader = csv.DictReader(handle)

        if not reader.fieldnames or not {"clip", "type", "time_seconds"} <= set(
                reader.fieldnames):
            raise TruthError("The truth file needs the columns: "
                             "clip,type,time_seconds")

        for number, row in enumerate(reader, 2):
            try:
                rows.append((row["clip"].strip(), row["type"].strip(),
                             float(row["time_seconds"])))
            except (TypeError, ValueError) as exc:
                raise TruthError(
                    f"Line {number}: time_seconds must be a number.") from exc

    return rows


def wilson(successes, total, z=1.96):
    """95% interval for a proportion; (None, None) when there is no data."""

    if total == 0:
        return None, None

    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) \
        / denominator

    return max(0.0, centre - margin), min(1.0, centre + margin)


def match(truth, detections, tolerance=3.0):
    """Count TP/FP/FN per type.

    truth, detections: lists of ``(clip, type, seconds)``. Returns
    ``{type: {"tp", "fp", "fn"}}``.
    """

    counts = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    free = list(truth)

    for clip, kind, seconds in sorted(detections):
        best = None

        for index, (t_clip, t_kind, t_seconds) in enumerate(free):
            if t_clip == clip and t_kind == kind:
                gap = abs(t_seconds - seconds)

                if gap <= tolerance and (best is None or gap < best[0]):
                    best = (gap, index)

        if best is None:
            counts[kind]["fp"] += 1
        else:
            free.pop(best[1])
            counts[kind]["tp"] += 1

    for _, kind, _ in free:
        counts[kind]["fn"] += 1

    return dict(counts)


def scores(counts):
    """Add precision, recall, F1 and the recall interval to each type."""

    result = {}

    for kind, c in sorted(counts.items()):
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision and recall else (0.0 if tp + fp + fn else None))
        low, high = wilson(tp, tp + fn)
        result[kind] = {**c, "precision": precision, "recall": recall,
                        "f1": f1, "recall_low": low, "recall_high": high}

    return result


def _pct(value):
    return "-" if value is None else f"{value * 100:.0f}%"


def to_markdown(result, clips, minutes, tolerance):
    lines = ["# Benchmark on real footage", "",
             f"{clips} clip(s), {minutes:.1f} minutes of video. A detection "
             f"counts when it is within {tolerance:g} s of a truth row of the "
             "same type.", "",
             "| Violation | Truth events | TP | FP | FN | Precision | Recall "
             "| Recall 95% range | F1 |",
             "|---|---|---|---|---|---|---|---|---|"]

    for kind, r in result.items():
        lines.append(
            f"| {kind} | {r['tp'] + r['fn']} | {r['tp']} | {r['fp']} | "
            f"{r['fn']} | {_pct(r['precision'])} | {_pct(r['recall'])} | "
            f"{_pct(r['recall_low'])} to {_pct(r['recall_high'])} | "
            f"{_pct(r['f1'])} |")

    lines += ["", "Small samples prove little: read the recall range, not "
              "just the percentage. Truth comes from a person watching the "
              "clips, so label carefully.", ""]

    return "\n".join(lines)


def find_clips(folder):
    folder = Path(folder)

    if not folder.is_dir():
        raise SystemExit(f"Folder not found: {folder}")

    return sorted(p for p in folder.iterdir()
                  if p.suffix.lower() in VIDEO_SUFFIXES)


def detect_all(clips, run_options, runner=None, out_dir=None):
    """Run each clip; returns (detections, total_video_seconds)."""

    import contextlib
    import io

    if runner is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import run_video
        runner = run_video.main

    out_dir = Path(out_dir or ROOT / "outputs" / "benchmark")
    out_dir.mkdir(parents=True, exist_ok=True)
    detections, seconds = [], 0.0

    for number, path in enumerate(clips, 1):
        print(f"[{number}/{len(clips)}] {path.name}", flush=True)
        argv = ["--input", str(path), "--output",
                str(out_dir / f"{path.stem}.mp4"), "--no-display",
                "--no-save", *run_options]

        with contextlib.redirect_stdout(io.StringIO()):
            summary = runner(argv)

        seconds += summary.frames / summary.video_fps if summary.video_fps else 0
        detections += [(path.name, v["type"], v["time_seconds"])
                       for v in summary.violations]
        detections += [(path.name, "collision", c["time_seconds"])
                       for c in summary.collisions]

    return detections, seconds


def main(argv=None, runner=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clips", required=True, help="folder of clips")
    parser.add_argument("--truth", required=True, help="truth CSV")
    parser.add_argument("--tolerance", type=float, default=3.0)
    parser.add_argument("--report", default=str(ROOT / "outputs" / "benchmark"),
                        help="report path without extension")
    args, run_options = parser.parse_known_args(argv)
    run_options = [o for o in run_options if o != "--"]

    try:
        truth = read_truth(args.truth)
    except TruthError as exc:
        raise SystemExit(str(exc))

    clips = find_clips(args.clips)

    if not clips:
        raise SystemExit("No video files found (mp4, avi, mov, mkv, m4v).")

    names = {c.name for c in clips}
    missing = sorted({t[0] for t in truth} - names)

    if missing:
        raise SystemExit(f"Truth rows name clips not in the folder: "
                         f"{', '.join(missing)}")

    detections, seconds = detect_all(clips, run_options, runner)
    result = scores(match(truth, detections, args.tolerance))
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    text = to_markdown(result, len(clips), seconds / 60, args.tolerance)
    report.with_suffix(".md").write_text(text, encoding="utf-8")
    report.with_suffix(".json").write_text(json.dumps(
        {"clips": len(clips), "video_seconds": round(seconds, 1),
         "tolerance_seconds": args.tolerance, "types": result}, indent=2),
        encoding="utf-8")
    print("\n" + text)
    print(f"Saved: {report.with_suffix('.md')}")

    return result


if __name__ == "__main__":
    main()
