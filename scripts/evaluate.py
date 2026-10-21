"""Measure how well the checks work against events you labelled by hand.

The project plan asks for precision and recall on labelled test videos. Watch
a clip, write down when each violation happens, then run:

    python scripts/evaluate.py --video clip.mp4 --truth truth.csv --speed --collisions

``truth.csv`` has one row per real event:

    type,time_seconds
    red_light,12.4
    speeding,31.0
    collision,48.2

``type`` is red_light, speeding, wrong_way or collision. ``time_seconds`` is
when it happens in the video. A detection counts as correct when it is the
same type and within ``--tolerance`` seconds (default 1.0) of a labelled
event. All the options of run_video.py work here too (stop line, speed lines,
signal and so on); see ``python scripts/evaluate.py --help``.

Results are not saved to the database.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import run_video

EVENT_TYPES = ("red_light", "speeding", "wrong_way", "collision")


def load_truth(path):
    """Read the labelled events: a list of ``(type, time_seconds)``."""

    events = []

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)

        if not reader.fieldnames or not {"type", "time_seconds"} <= set(
            name.strip() for name in reader.fieldnames
        ):
            raise ValueError(
                "The truth file needs the columns: type,time_seconds"
            )

        for number, row in enumerate(reader, start=2):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}

            if not any(row.values()):
                continue

            if row["type"] not in EVENT_TYPES:
                raise ValueError(
                    f"Line {number}: type must be one of "
                    f"{', '.join(EVENT_TYPES)} (got '{row['type']}')."
                )

            try:
                seconds = float(row["time_seconds"])
            except ValueError:
                raise ValueError(
                    f"Line {number}: time_seconds must be a number "
                    f"(got '{row['time_seconds']}')."
                ) from None

            if seconds < 0:
                raise ValueError(
                    f"Line {number}: time_seconds cannot be negative."
                )

            events.append((row["type"], seconds))

    return events


def predictions_from_summary(summary):
    """The pipeline's detections as ``(type, time_seconds)``."""

    found = [(v["type"], float(v["time_seconds"])) for v in summary.violations]
    found += [("collision", float(c["time_seconds"]))
              for c in summary.collisions]

    return found


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _scores(tp, fp, fn):
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall else (0.0 if tp + fp + fn else None)
    )

    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1}


def match_times(predicted, truth, tolerance):
    """Pair predictions with labelled times; returns ``(tp, fp, fn)``.

    Each labelled event is matched, in time order, with the closest
    prediction within ``tolerance`` seconds that is not already used, so one
    detection can never be counted for two events.
    """

    unused = sorted(predicted)
    tp = 0

    for moment in sorted(truth):
        best = None

        for index, candidate in enumerate(unused):
            gap = abs(candidate - moment)

            if gap <= tolerance and (best is None or gap < best[0]):
                best = (gap, index)

        if best is not None:
            unused.pop(best[1])
            tp += 1

    return tp, len(unused), len(truth) - tp


def score(predictions, truth, tolerance=1.0, checked=EVENT_TYPES):
    """Precision, recall and F1 per event type, and overall.

    Only the types in ``checked`` are scored: a check that was switched off
    would otherwise show every labelled event of that type as missed.
    """

    by_type = {}
    totals = [0, 0, 0]

    for kind in checked:
        predicted = [t for k, t in predictions if k == kind]
        labelled = [t for k, t in truth if k == kind]

        if not predicted and not labelled:
            continue

        tp, fp, fn = match_times(predicted, labelled, tolerance)
        by_type[kind] = _scores(tp, fp, fn)
        totals = [totals[0] + tp, totals[1] + fp, totals[2] + fn]

    return {"by_type": by_type, "overall": _scores(*totals),
            "tolerance_seconds": tolerance}


def enabled_types(args):
    """Event types the chosen options actually check."""

    types = ["red_light"]

    if args.speed:
        types.append("speeding")

    if args.wrong_way:
        types.append("wrong_way")

    if args.collisions:
        types.append("collision")

    return types


def _percent(value):
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


def format_report(result, summary, skipped=()):
    lines = [
        f"{'Event':<11} {'Correct':>8} {'False':>6} {'Missed':>7} "
        f"{'Precision':>10} {'Recall':>8} {'F1':>7}",
        "-" * 62,
    ]

    rows = list(result["by_type"].items()) + [("OVERALL", result["overall"])]

    for name, s in rows:
        lines.append(
            f"{name:<11} {s['tp']:>8} {s['fp']:>6} {s['fn']:>7} "
            f"{_percent(s['precision']):>10} {_percent(s['recall']):>8} "
            f"{_percent(s['f1']):>7}"
        )

    lines += [
        "",
        f"Matching window: +/- {result['tolerance_seconds']:g} s.   "
        "Correct = detected and labelled; False = detected but not "
        "labelled; Missed = labelled but not detected.",
        f"Speed: {summary.processing_fps:.1f} frames per second processed "
        f"({summary.frames} frames; the video plays at "
        f"{summary.video_fps:.0f} FPS).",
    ]

    for kind, count in skipped:
        lines.append(
            f"Not scored: {count} labelled {kind} event(s), because that "
            "check was not turned on."
        )

    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Score the checks against hand-labelled events.",
        parents=[run_video.build_parser(add_help=False)],
    )
    parser.add_argument("--video", help="video to analyze "
                        "(same as --input)")
    parser.add_argument("--truth", required=True,
                        help="CSV of labelled events: type,time_seconds")
    parser.add_argument("--tolerance", type=float, default=1.0,
                        help="seconds either side that still counts as the "
                             "same event (default 1.0)")
    parser.add_argument("--report", help="also write the results to this "
                        "JSON file")

    return parser


def main(argv=None, **components):
    """``components`` (detector, tracker, emergency_detector) are for tests."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.tolerance < 0:
        parser.error("--tolerance cannot be negative.")

    if args.video:
        args.input = args.video

    if run_video.is_live(args.input):
        parser.error("evaluate.py needs a video file, not a live stream.")

    # Evaluation must never write to the real database or open windows.
    args.no_save = True
    args.no_display = True
    args.send_alerts = False

    try:
        truth = load_truth(args.truth)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    checked = enabled_types(args)
    skipped = [(kind, sum(1 for k, _ in truth if k == kind))
               for kind in EVENT_TYPES
               if kind not in checked and any(k == kind for k, _ in truth)]

    summary = run_video.run(args, parser, **components)

    result = score(predictions_from_summary(summary), truth,
                   args.tolerance, checked)

    print()
    print(format_report(result, summary, skipped))

    if args.report:
        report = dict(result)
        report["video"] = str(args.input)
        report["frames"] = summary.frames
        report["processing_fps"] = round(summary.processing_fps, 2)
        report["not_scored"] = dict(skipped)
        Path(args.report).write_text(json.dumps(report, indent=2))
        print(f"Wrote {args.report}")

    return result


if __name__ == "__main__":
    main()
    sys.exit(0)
