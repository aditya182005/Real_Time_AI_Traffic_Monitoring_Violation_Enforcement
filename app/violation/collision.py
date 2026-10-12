import os
from datetime import datetime, timezone
from pathlib import Path

import cv2
import supervision as sv
from ultralytics import YOLO

from app import paths
from app.alerts import twilio_alert
from app.violation.collision_logic import (  # noqa: F401  (calculate_iou re-exported)
    CollisionHeuristic,
    calculate_iou,
)
from app.violation.violation_logger import (
    log_collision_event,
    setup_database,
)

ROOT = Path(__file__).resolve().parents[2]

VIDEO_PATH = ROOT / "data" / "videos" / "traffic.mp4"
# Bare model name: Ultralytics downloads it on first use (*.pt is git-ignored).
MODEL_PATH = "yolov8n.pt"
OUTPUT_DIR = paths.OUTPUT_DIR / "collisions"

CAMERA_ID = os.getenv("CAMERA_ID", "CAM-01")
CONFIDENCE = 0.35
VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck


def main():
    if not VIDEO_PATH.exists():
        raise FileNotFoundError(f"Video not found: {VIDEO_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_database()

    model = YOLO(MODEL_PATH)
    tracker = sv.ByteTrack()
    heuristic = CollisionHeuristic()
    cap = cv2.VideoCapture(str(VIDEO_PATH))

    frame_number = 0

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        frame_number += 1

        result = model.predict(
            frame,
            classes=VEHICLE_CLASSES,
            conf=CONFIDENCE,
            verbose=False
        )[0]

        detections = sv.Detections.from_ultralytics(result)
        detections = tracker.update_with_detections(detections)

        vehicles = []

        if detections.tracker_id is not None:
            for i, box in enumerate(detections.xyxy):
                vehicles.append((
                    int(detections.tracker_id[i]),
                    box.tolist()
                ))

        for pair, box_a, box_b in heuristic.update(vehicles):
            id_a, id_b = pair
            timestamp = datetime.now(timezone.utc).isoformat()
            filename = f"possible_collision_{id_a}_{id_b}_{frame_number}.jpg"
            evidence_path = OUTPUT_DIR / filename

            x1, y1, x2, y2 = map(int, box_a)
            a1, b1, a2, b2 = map(int, box_b)

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.rectangle(frame, (a1, b1), (a2, b2), (0, 0, 255), 2)

            cv2.putText(
                frame,
                "POSSIBLE COLLISION - VERIFY",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2
            )

            cv2.imwrite(str(evidence_path), frame)

            event_id = log_collision_event(
                id_a,
                id_b,
                evidence_path,
                camera_id=CAMERA_ID,
                source=VIDEO_PATH.name,
            )

            message = (
                f"Traffic Agent [{CAMERA_ID}] {timestamp}: possible "
                f"collision between vehicle tracks {id_a} and {id_b}. "
                f"Please verify the incident."
            )

            print(message)

            # Network call: sent off the video loop, outcome stored on the
            # record (see app/alerts/twilio_alert.py).
            twilio_alert.dispatch(event_id, message)

        cv2.imshow("Traffic Agent - Collision Monitoring", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
