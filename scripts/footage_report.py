"""Run a folder of real clips through the pipeline and report what it found.

Put your clips in two folders:

    clips/normal/      traffic with NO ambulance, fire truck or police car
    clips/emergency/   clips that DO contain an emergency vehicle

Then:

    python scripts/footage_report.py --normal clips/normal --emergency clips/emergency

Every emergency detection in a "normal" clip is a false alarm, so the report
gives false alarms per hour of video there, and in the "emergency" clips how
many clips were detected at all (clip-level hit rate). Violation counts are
listed per clip so you can check a few by hand. Extra options after ``--`` go
to run_video.py, for example ``-- --speed --wrong-way --collisions``.

The report is written to outputs/footage_report.md (and .json).
"""

import argparse
import contextlib
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}


def find_clips(folder):
    folder = Path(folder)

    if not folder.is_dir():
        raise SystemExit(f"Folder not found: {folder}")

    return sorted(p for p in folder.iterdir()
                  if p.suffix.lower() in VIDEO_SUFFIXES)


def summarize_clip(path, group, summary):
    """Reduce a VideoSummary to plain numbers."""

    video_seconds = (
        summary.frames / summary.video_fps if summary.video_fps else 0.0
    )

    return {
        "clip": Path(path).name,
        "group": group,
        "frames": summary.frames,
        "video_seconds": round(video_seconds, 1),
        "processing_fps": round(summary.processing_fps, 1),
        "emergency_events": [
            {"class": e["class_name"], "confidence": e["confidence"],
             "time_seconds": round(e["time_seconds"], 1)}
            for e in summary.emergency_events
        ],
        "violations": dict(Counter(v["type"] for v in summary.violations)),
        "collisions": len(summary.collisions),
    }


def aggregate(rows):
    normal = [r for r in rows if r["group"] == "normal"]
    positive = [r for r in rows if r["group"] == "emergency"]

    normal_hours = sum(r["video_seconds"] for r in normal) / 3600
    false_alarms = sum(len(r["emergency_events"]) for r in normal)
    detected = sum(1 for r in positive if r["emergency_events"])

    return {
        "normal_clips": len(normal),
        "normal_video_minutes": round(normal_hours * 60, 1),
        "false_alarms": false_alarms,
        "false_alarms_per_hour": (
            round(false_alarms / normal_hours, 2) if normal_hours else None
        ),
        "normal_clips_with_false_alarm": sum(
            1 for r in normal if r["emergency_events"]),
        "emergency_clips": len(positive),
        "emergency_clips_detected": detected,
        "emergency_hit_rate": (
            round(detected / len(positive), 2) if positive else None
        ),
    }


def to_markdown(rows, totals):
    lines = ["# Real-footage report", ""]

    lines += [
        "| Measure | Value |", "|---|---|",
        f"| Normal clips (no emergency vehicle) | {totals['normal_clips']} "
        f"({totals['normal_video_minutes']} min) |",
        f"| Emergency false alarms | {totals['false_alarms']} "
        f"({totals['normal_clips_with_false_alarm']} clips affected) |",
        f"| False alarms per hour of video | "
        f"{totals['false_alarms_per_hour']} |",
        f"| Emergency clips | {totals['emergency_clips']} |",
        f"| Emergency clips detected | {totals['emergency_clips_detected']} "
        f"(hit rate {totals['emergency_hit_rate']}) |",
        "", "## Per clip", "",
        "| Clip | Group | Video s | FPS | Emergency events | Violations | "
        "Collisions |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in rows:
        events = ", ".join(
            f"{e['class']} {e['confidence']:.2f} @ {e['time_seconds']}s"
            for e in r["emergency_events"]) or "-"
        violations = ", ".join(
            f"{k} x{v}" for k, v in sorted(r["violations"].items())) or "-"
        lines.append(
            f"| {r['clip']} | {r['group']} | {r['video_seconds']} | "
            f"{r['processing_fps']} | {events} | {violations} | "
            f"{r['collisions']} |")

    lines += ["", "Review every emergency event in a normal clip by eye: "
              "that is what makes it a false alarm.", ""]

    return "\n".join(lines)


def run_clips(clips, run_options, runner=None, out_dir=None):
    """clips: list of (path, group). Returns one row per clip."""

    if runner is None:
        import run_video
        runner = run_video.main

    out_dir = Path(out_dir or ROOT / "outputs" / "footage")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    for number, (path, group) in enumerate(clips, 1):
        print(f"[{number}/{len(clips)}] {path.name} ({group})", flush=True)
        argv = [
            "--input", str(path), "--output", str(out_dir / f"{path.stem}.mp4"),
            "--no-display", "--no-save", "--emergency", *run_options,
        ]

        with contextlib.redirect_stdout(io.StringIO()):
            summary = runner(argv)

        rows.append(summarize_clip(path, group, summary))

    return rows


def main(argv=None, runner=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--normal", help="folder of clips with no emergency vehicle")
    parser.add_argument("--emergency", help="folder of clips with an emergency vehicle")
    parser.add_argument("--report", default=str(ROOT / "outputs" / "footage_report"),
                        help="report path without extension")
    args, run_options = parser.parse_known_args(argv)
    run_options = [o for o in run_options if o != "--"]

    if not args.normal and not args.emergency:
        parser.error("give --normal and/or --emergency")

    clips = []

    for folder, group in ((args.normal, "normal"), (args.emergency, "emergency")):
        if folder:
            clips += [(p, group) for p in find_clips(folder)]

    if not clips:
        raise SystemExit("No video files found (mp4, avi, mov, mkv, m4v).")

    rows = run_clips(clips, run_options, runner)
    totals = aggregate(rows)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    text = to_markdown(rows, totals)
    report.with_suffix(".md").write_text(text, encoding="utf-8")
    report.with_suffix(".json").write_text(
        json.dumps({"totals": totals, "clips": rows}, indent=2),
        encoding="utf-8")
    print("\n" + text)
    print(f"Saved: {report.with_suffix('.md')}")

    return totals


if __name__ == "__main__":
    main()
