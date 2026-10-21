"""Manual check: run from the project root, e.g.
    python scripts/manual_checks/test_emergency.py
Not part of the automated tests (see tests/)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import ultralytics

model = ultralytics.YOLO("models/emergency_vehicle.pt")

results = model("data/images/test.jpg")

results[0].save(
    filename="outputs/detections/emergency_test.jpg"
)

print("Emergency vehicle detection completed.")