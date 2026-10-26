"""The fine table.

The built-in amounts are demo values. To use your own, point ``FINES_FILE`` at
a JSON file (and keep it under version control with the rule it came from)::

    {
      "red_light": 1000,
      "wrong_way": 1500,
      "no_helmet": 1000,
      "speeding": {"base": 500, "per_10_kmh": 100}
    }

Any key you leave out keeps its demo value. A bad file stops the app with a
clear message rather than silently charging the wrong amount.
"""

import json
import os
from pathlib import Path

DEMO = {
    "red_light": 1000,
    "wrong_way": 1500,
    "no_helmet": 1000,
    "speeding": {"base": 500, "per_10_kmh": 100},
}


class FineConfigError(ValueError):
    """The fines file is missing, unreadable or has invalid amounts."""


def _amount(value, where):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FineConfigError(
            f"{where} must be a whole number of 0 or more, got {value!r}.")

    return value


def parse(data):
    """Merge a loaded JSON object over the demo values, with validation."""

    if not isinstance(data, dict):
        raise FineConfigError("The fines file must contain a JSON object.")

    unknown = set(data) - set(DEMO)

    if unknown:
        raise FineConfigError(
            f"Unknown fine type(s): {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(DEMO)}.")

    table = {
        "red_light": DEMO["red_light"],
        "wrong_way": DEMO["wrong_way"],
        "no_helmet": DEMO["no_helmet"],
        "speeding": dict(DEMO["speeding"]),
    }

    for key in ("red_light", "wrong_way", "no_helmet"):
        if key in data:
            table[key] = _amount(data[key], key)

    if "speeding" in data:
        speeding = data["speeding"]

        if not isinstance(speeding, dict) or set(speeding) - {"base", "per_10_kmh"}:
            raise FineConfigError(
                'speeding must be {"base": N, "per_10_kmh": N}.')

        for key, value in speeding.items():
            table["speeding"][key] = _amount(value, f"speeding.{key}")

    return table


def load(path=None):
    """The active fine table (demo values unless ``FINES_FILE`` is set)."""

    path = path or os.getenv("FINES_FILE", "").strip()

    if not path:
        return parse({})

    file = Path(path).expanduser()

    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FineConfigError(f"Cannot read FINES_FILE {file}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FineConfigError(f"FINES_FILE {file} is not valid JSON: {exc}") from exc

    return parse(data)
