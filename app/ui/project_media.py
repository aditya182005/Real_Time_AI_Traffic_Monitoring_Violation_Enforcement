"""Photos and videos that live in the project folder.

The Analyze page can use files from these folders without uploading them:

* ``data/samples``   bundled sample pictures
* ``data/videos``    bundled videos
* ``data/my_media``  your own photos and videos (drop files here)

Choices are built from a directory listing and looked up by label, so a
typed or tampered name can never point outside these folders.
"""

from pathlib import Path

from app import media

ROOT = Path(__file__).resolve().parents[2]
FOLDERS = ("my_media", "samples", "videos")      # my own files first
MAX_FILES = 200


def _list(extensions):
    found = {}

    for folder in FOLDERS:
        base = ROOT / "data" / folder

        if not base.is_dir():
            continue

        for path in sorted(base.iterdir()):
            if path.is_file() and path.suffix.lower() in extensions:
                found[f"{folder}/{path.name}"] = path

    return dict(list(found.items())[:MAX_FILES])


def images():
    """{label: path} for pictures in the project folders."""

    return _list(media.ALLOWED_IMAGE_EXTENSIONS)


def videos():
    """{label: path} for videos in the project folders."""

    return _list(media.ALLOWED_VIDEO_EXTENSIONS)


class ProjectFile:
    """Looks like an uploaded file (``name``, ``getvalue``) but is on disk."""

    def __init__(self, label, path):
        self.name = Path(label).name
        self.path = Path(path)

    def getvalue(self):
        return self.path.read_bytes()


# What the bundled demo video should produce, and the settings that make it so.
DEMO_VIDEO = "demo_all_checks.mp4"
DEMO_EXPECTED = (
    ("Red light", "1", "at about 2.5 s: a car crosses the stop line on red"),
    ("Speeding", "1", "at about 9.9 s: 45 km/h in a 40 limit"),
    ("Wrong way", "1", "at about 12.8 s: a car drives up the screen"),
    ("Possible collision", "1", "at about 20 s: a car hits a stopped van"),
    ("Emergency vehicles", "3", "ambulance, fire truck, police car "
                               "(needs the emergency model)"),
    ("The van at 8 s", "0", "it crosses on green: no violation is correct"),
)
DEMO_SETTINGS = {
    "stop_line_pct": 60,
    "red_s": 6, "green_s": 6,
    "check_speed": True, "line_a": 45, "line_b": 75,
    "distance_m": 10.0, "limit_kmh": 40,
    "check_wrong_way": True, "lane_range": (0, 100),
    "check_collisions": True,
}
