"""Manual check: run from the project root, e.g.
    python scripts/manual_checks/test_emergency_video.py
Not part of the automated tests (see tests/)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cv2
from ultralytics import YOLO

model = YOLO("models/emergency_vehicle.pt")

cap = cv2.VideoCapture("data/videos/traffic.mp4")

while True:

    ret, frame = cap.read()

    if not ret:
        break

    results = model(frame, verbose=False)

    annotated = results[0].plot()

    cv2.imshow(
        "Emergency Vehicle Detection",
        annotated
    )

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


cap.release()
cv2.destroyAllWindows()