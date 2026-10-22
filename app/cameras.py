"""Per-camera settings (calibration profiles).

Every camera sees a different road, so its stop line, speed lines and the
real distance between them differ. Keep them in one JSON file, point
``CAMERAS_FILE`` at it, and select a profile by name::

    {
      "NH-4-north": {
        "stop_line_pct": 62,
        "signal_mode": "lamp",
        "lamp_roi_pct": [82, 4, 90, 22],
        "check_speed": true,
        "speed_line_a_pct": 45,
        "speed_line_b_pct": 75,
        "speed_distance_m": 12.5,
        "speed_limit_kmh": 50,
        "expected_direction": "down"
      }
    }

Use it with ``python scripts/run_video.py --profile NH-4-north``. The
profile's values replace the command-line defaults, and the camera ID is set
to the profile name. Unknown keys and wrong types are refused, so a typo
cannot silently fall back to a default.
"""

import dataclasses
import json
import os
from pathlib import Path

from app.analysis import VideoSettings

# Not calibration: chosen per run, not per camera.
EXCLUDED = {"camera_id", "send_alerts", "save_to_db", "use_emergency",
            "read_plates"}


class ProfileError(ValueError):
    """A missing file or profile, or an invalid value."""


def allowed_fields():
    return {f.name: f for f in dataclasses.fields(VideoSettings)
            if f.name not in EXCLUDED}


def load_profiles(path=None):
    path = path or os.getenv("CAMERAS_FILE", "").strip()

    if not path:
        raise ProfileError("Set CAMERAS_FILE to your cameras JSON file.")

    file = Path(path).expanduser()

    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProfileError(f"Cannot read {file}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{file} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ProfileError(f"{file} must contain a JSON object of profiles.")

    return data


def _coerce(name, value, default):
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ProfileError(f"{name} must be true or false.")

        return value

    if isinstance(default, tuple):
        if not isinstance(value, (list, tuple)) or len(value) != len(default) \
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           for v in value):
            raise ProfileError(f"{name} must be a list of {len(default)} numbers.")

        return tuple(float(v) for v in value)

    if isinstance(default, str):
        if not isinstance(value, str):
            raise ProfileError(f"{name} must be text.")

        return value

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{name} must be a number.")

    return float(value)


def settings_for(name, path=None, base=None):
    """VideoSettings for the named profile (``base`` is the starting point)."""

    profiles = load_profiles(path)

    if name not in profiles:
        known = ", ".join(sorted(profiles)) or "none"
        raise ProfileError(f"No profile named {name!r}. Available: {known}.")

    profile = profiles[name]

    if not isinstance(profile, dict):
        raise ProfileError(f"Profile {name!r} must be a JSON object.")

    fields = allowed_fields()
    unknown = set(profile) - set(fields)

    if unknown:
        raise ProfileError(
            f"Profile {name!r} has unknown key(s): "
            f"{', '.join(sorted(unknown))}. Allowed: {', '.join(sorted(fields))}.")

    settings = dataclasses.replace(base or VideoSettings(), camera_id=name)
    changes = {key: _coerce(key, value, getattr(settings, key))
               for key, value in profile.items()}

    return dataclasses.replace(settings, **changes)
