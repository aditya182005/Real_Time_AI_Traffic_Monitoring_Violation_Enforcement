"""Check that this computer is ready to run Traffic Agent.

    python check_setup.py            # quick checks (a second or two)
    python check_setup.py --full     # also loads YOLO and runs it on a photo

Each line is OK, WARN (something works but a feature is off) or FAIL
(the app will not run). The exit status is 1 if anything failed, so it can
also be used in a script.

``--full`` is the real end-to-end test of the detection stack: it loads the
YOLO model (downloading yolov8n.pt the first time, so it needs internet),
detects vehicles in data/images/test.jpg and passes them through ByteTrack.
"""

import argparse
import importlib.util
import shutil
import sys
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent

OK, WARN, FAIL = "ok", "warn", "fail"

MIN_PYTHON = (3, 10)

# (import name, pip name, what stops working without it)
REQUIRED_PACKAGES = (
    ("ultralytics", "ultralytics", "vehicle detection"),
    ("supervision", "supervision", "vehicle tracking"),
    ("cv2", "opencv-python", "reading and writing video"),
    ("streamlit", "streamlit", "the dashboard"),
    ("numpy", "numpy", "everything"),
    ("pandas", "pandas", "the dashboard tables"),
    ("PIL", "pillow", "reading uploaded images"),
    ("dotenv", "python-dotenv", "loading the .env file"),
)

OPTIONAL_PACKAGES = (
    ("twilio", "twilio", "SMS and call alerts (they will not be sent)"),
)


@dataclass
class Check:
    status: str
    name: str
    detail: str = ""
    fix: str = ""


def _installed_version(*dist_names):
    for name in dist_names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue

    return "version unknown"


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# -- quick checks -------------------------------------------------------------

def check_python():
    found = sys.version_info[:2]
    label = f"{found[0]}.{found[1]}"

    if found >= MIN_PYTHON:
        return [Check(OK, "Python", label)]

    return [Check(
        FAIL, "Python", f"{label} is too old",
        f"Install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
    )]


def check_packages():
    checks = []

    for module, pip_name, purpose in REQUIRED_PACKAGES:
        if _has_module(module):
            dists = (pip_name, "opencv-python-headless") \
                if module == "cv2" else (pip_name,)
            checks.append(Check(OK, pip_name, _installed_version(*dists)))
        else:
            checks.append(Check(
                FAIL, pip_name, f"missing: needed for {purpose}",
                "pip install -r requirements.txt",
            ))

    for module, pip_name, purpose in OPTIONAL_PACKAGES:
        if _has_module(module):
            checks.append(Check(OK, pip_name, _installed_version(pip_name)))
        else:
            checks.append(Check(
                WARN, pip_name, f"missing: {purpose}", f"pip install {pip_name}",
            ))

    return checks


def check_video_playback():
    if shutil.which("ffmpeg"):
        return [Check(OK, "ffmpeg", "found on PATH")]

    if _has_module("imageio_ffmpeg"):
        return [Check(OK, "ffmpeg", "bundled with imageio-ffmpeg")]

    return [Check(
        WARN, "ffmpeg",
        "not found: annotated videos can be downloaded but not played "
        "in the browser",
        "pip install imageio-ffmpeg",
    )]


def check_files(root=ROOT):
    root = Path(root)
    checks = []

    sample = root / "data" / "videos" / "traffic.mp4"
    checks.append(
        Check(OK, "Sample video", "data/videos/traffic.mp4")
        if sample.is_file() else
        Check(WARN, "Sample video",
              "data/videos/traffic.mp4 is missing: the 'Try the sample "
              "video' button will not appear",
              "Restore it with: git checkout -- data/videos/traffic.mp4")
    )

    weights = root / "models" / "emergency_vehicle.pt"
    checks.append(
        Check(OK, "Emergency-vehicle model", "models/emergency_vehicle.pt")
        if weights.is_file() else
        Check(WARN, "Emergency-vehicle model",
              "models/emergency_vehicle.pt is missing: emergency detection "
              "and the signal override are off",
              "python train_emergency.py   (a GPU, for example Google "
              "Colab, makes this much faster)")
    )

    return checks


def check_twilio_settings():
    try:
        from app.alerts import twilio_alert
    except Exception as exc:  # pragma: no cover - defensive
        return [Check(WARN, "Twilio settings",
                      f"could not be checked ({type(exc).__name__})")]

    if not twilio_alert.is_configured():
        missing = [name for name, present in
                   twilio_alert.config_status().items() if not present]

        return [Check(
            WARN, "Twilio settings",
            "not set up: collision alerts will be skipped "
            f"(missing {', '.join(missing)})",
            "Copy .env.example to .env and fill it in. "
            "See the README, section 'Twilio alerts'.",
        )]

    problems = twilio_alert.config_problems()

    if problems:
        return [Check(WARN, "Twilio settings", problem,
                      "Fix it in .env, then run: "
                      "python -m app.alerts.twilio_alert")
                for problem in problems]

    return [Check(
        OK, "Twilio settings",
        "all four set and valid (nothing sent; run "
        "`python -m app.alerts.twilio_alert --send` to test for real)",
    )]


def check_writable(root=None):
    """The database and outputs folders must be writable.

    By default these follow TRAFFIC_AGENT_DATA_DIR (see app/paths.py).
    """

    if root is None:
        from app import paths

        folders = (("Database folder", paths.DATA_DIR),
                   ("Outputs folder", paths.OUTPUT_DIR))
    else:
        root = Path(root)
        folders = (("Database folder", root),
                   ("Outputs folder", root / "outputs"))

    checks = []

    for label, folder in folders:
        try:
            folder.mkdir(parents=True, exist_ok=True)

            with tempfile.NamedTemporaryFile(dir=folder):
                pass

            checks.append(Check(OK, label, "writable"))
        except OSError as exc:
            checks.append(Check(
                FAIL, label, f"cannot write to {folder} ({exc.strerror})",
                "Check the folder's permissions.",
            ))

    return checks


def quick_checks(root=ROOT):
    return (
        check_python()
        + check_packages()
        + check_video_playback()
        + check_files(root)
        + check_twilio_settings()
        + check_writable()
    )


# -- full check: run the real models ------------------------------------------

def smoke_test(root=ROOT, detector=None, tracker=None, emergency=None):
    """Run the detection stack on the bundled photo.

    The three components can be passed in for testing; by default the real
    YOLO model, ByteTrack and (if its weights exist) the emergency model
    are used.
    """

    root = Path(root)
    checks = []
    image_path = root / "data" / "images" / "test.jpg"

    try:
        import cv2

        image = cv2.imread(str(image_path))
    except ImportError:
        return [Check(FAIL, "Detection test", "OpenCV is not installed",
                      "pip install -r requirements.txt")]

    if image is None:
        return [Check(WARN, "Detection test",
                      f"{image_path} is missing or unreadable, so the test "
                      "was skipped")]

    # 1. Vehicle detection ---------------------------------------------------
    try:
        if detector is None:
            from app.detection.detector import VehicleDetector

            detector = VehicleDetector()

        detections = detector.detect(image)
    except Exception as exc:
        return [Check(
            FAIL, "Vehicle detection", f"{type(exc).__name__}: {exc}",
            "The first run downloads yolov8n.pt and needs internet. "
            "Also check: pip install -r requirements.txt",
        )]

    names = sorted({d["class_name"] for d in detections})
    checks.append(Check(
        OK, "Vehicle detection",
        f"found {len(detections)} vehicle(s) in test.jpg"
        + (f" ({', '.join(names)})" if names else ""),
    ))

    # 2. Tracking ------------------------------------------------------------
    try:
        if tracker is None:
            from app.tracking.tracker import VehicleTracker

            tracker = VehicleTracker()

        tracked = None

        for _ in range(3):      # a track needs a few frames to be confirmed
            tracked = tracker.update(detections)

        _ = len(tracked.xyxy)   # must be a real Detections object
    except Exception as exc:
        checks.append(Check(
            FAIL, "Vehicle tracking", f"{type(exc).__name__}: {exc}",
            'pip install "supervision>=0.20,<0.31"',
        ))
    else:
        checks.append(Check(
            OK, "Vehicle tracking",
            f"ByteTrack accepted the detections ({len(tracked.xyxy)} "
            "confirmed track(s) after 3 identical frames)",
        ))

    # 3. Emergency model (optional) ---------------------------------------
    weights = root / "models" / "emergency_vehicle.pt"

    if emergency is None and not weights.is_file():
        checks.append(Check(
            WARN, "Emergency detection",
            "skipped: models/emergency_vehicle.pt is missing",
            "python train_emergency.py",
        ))

        return checks

    try:
        if emergency is None:
            from app.detection.emergency_detector import EmergencyDetector

            emergency = EmergencyDetector(weights)

        found = emergency.detect(image)
    except Exception as exc:
        checks.append(Check(
            FAIL, "Emergency detection", f"{type(exc).__name__}: {exc}",
            "Re-run train_emergency.py, or remove the weights file.",
        ))
    else:
        checks.append(Check(
            OK, "Emergency detection",
            f"model loaded; {len(found)} emergency vehicle(s) in test.jpg",
        ))

    return checks


# -- output -------------------------------------------------------------------

LABELS = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}


def format_report(checks):
    lines = []

    for check in checks:
        line = f"{LABELS[check.status]} {check.name}"

        if check.detail:
            line += f": {check.detail}"

        lines.append(line)

        if check.fix and check.status != OK:
            lines.append(f"        -> {check.fix}")

    failed = sum(c.status == FAIL for c in checks)
    warned = sum(c.status == WARN for c in checks)

    lines.append("")

    if failed:
        lines.append(f"{failed} problem(s) must be fixed before the app runs.")
    elif warned:
        lines.append(
            f"Ready to run. {warned} optional item(s) above are switched off."
        )
    else:
        lines.append("Everything is ready.")

    return "\n".join(lines)


def main(argv=None, root=ROOT, **components):
    parser = argparse.ArgumentParser(
        description="Check that this computer is ready to run Traffic Agent."
    )
    parser.add_argument(
        "--full", action="store_true",
        help="also load the models and run them on data/images/test.jpg",
    )
    args = parser.parse_args(argv)

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    checks = quick_checks(root)

    if args.full:
        blocking = [c for c in checks if c.status == FAIL
                    and c.name in {p[1] for p in REQUIRED_PACKAGES}]

        if blocking:
            checks.append(Check(
                WARN, "Detection test",
                "skipped because required packages are missing",
                "pip install -r requirements.txt",
            ))
        else:
            checks += smoke_test(root, **components)

    print(format_report(checks))

    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
