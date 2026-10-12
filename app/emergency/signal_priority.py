
import cv2
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import supervision as sv
from ultralytics import YOLO

from app import paths

ROOT = Path(__file__).resolve().parents[2]

VIDEO_PATH = ROOT / "data" / "videos" / "traffic.mp4"
MODEL_PATH = ROOT / "models" / "emergency_vehicle.pt"
DB_PATH = paths.DB_PATH
OUTPUT_DIR = paths.OUTPUT_DIR / "priority"

CONFIDENCE_THRESHOLD = 0.65
CONFIRM_FRAMES = 3

# Change these coordinates to match your video.
# This rectangle represents the intersection approach zone.
ROI_X1 = 300
ROI_Y1 = 150
ROI_X2 = 900
ROI_Y2 = 650


def setup_database():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS priority_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER NOT NULL,
                vehicle_class TEXT NOT NULL,
                confidence REAL NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)


def log_priority(track_id, vehicle_class, confidence):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO priority_events (
                track_id, vehicle_class, confidence,
                event_type, timestamp
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            track_id,
            vehicle_class,
            round(confidence, 3),
            "SIMULATED_PRIORITY_REQUEST",
            datetime.now(timezone.utc).isoformat()
        ))


def main():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Custom model not found: {MODEL_PATH}"
        )

    if not VIDEO_PATH.exists():
        raise FileNotFoundError(
            f"Traffic video not found: {VIDEO_PATH}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_database()

    model = YOLO(str(MODEL_PATH))
    tracker = sv.ByteTrack()
    cap = cv2.VideoCapture(str(VIDEO_PATH))

    # Count consecutive frames inside the ROI per track.
    frame_counts = {}
    logged_tracks = set()

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        result = model.predict(
            frame,
            conf=CONFIDENCE_THRESHOLD,
            imgsz=640,
            verbose=False
        )[0]

        detections = sv.Detections.from_ultralytics(result)

        # Keep only confident detections.
        if detections.confidence is not None:
            detections = detections[
                detections.confidence >= CONFIDENCE_THRESHOLD
            ]

        detections = tracker.update_with_detections(detections)

        current_roi_tracks = set()
        priority_active = False

        # Draw the intersection approach region.
        cv2.rectangle(
            frame,
            (ROI_X1, ROI_Y1),
            (ROI_X2, ROI_Y2),
            (255, 255, 0),
            2
        )

        if detections.tracker_id is not None:
            for i, box in enumerate(detections.xyxy):
                track_id = int(detections.tracker_id[i])
                class_id = int(detections.class_id[i])
                confidence = float(detections.confidence[i])
                vehicle_class = model.names[class_id]

                x1, y1, x2, y2 = map(int, box)
                center_x = (x1 + x2) // 2
                center_y = (y1 + y2) // 2

                in_roi = (
                    ROI_X1 <= center_x <= ROI_X2
                    and ROI_Y1 <= center_y <= ROI_Y2
                )

                if in_roi:
                    current_roi_tracks.add(track_id)
                    frame_counts[track_id] = (
                        frame_counts.get(track_id, 0) + 1
                    )
                else:
                    frame_counts[track_id] = 0

                confirmed = (
                    in_roi
                    and frame_counts.get(track_id, 0) >= CONFIRM_FRAMES
                )

                color = (0, 255, 0)

                if confirmed:
                    priority_active = True
                    color = (0, 0, 255)

                    if track_id not in logged_tracks:
                        log_priority(
                            track_id,
                            vehicle_class,
                            confidence
                        )
                        logged_tracks.add(track_id)

                        print(
                            f"Priority requested: {vehicle_class}, "
                            f"ID={track_id}, "
                            f"confidence={confidence:.2f}"
                        )

                label = f"{vehicle_class} ID:{track_id} {confidence:.2f}"

                cv2.rectangle(
                    frame, (x1, y1), (x2, y2), color, 2
                )
                cv2.putText(
                    frame,
                    label,
                    (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    2
                )

        # Reset confirmation for tracks no longer inside the ROI.
        for track_id in list(frame_counts):
            if track_id not in current_roi_tracks:
                frame_counts[track_id] = 0

        signal_status = (
            "PRIORITY REQUESTED - SIMULATION"
            if priority_active
            else "NORMAL SIGNAL - SIMULATION"
        )

        cv2.putText(
            frame,
            signal_status,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255) if priority_active else (0, 255, 0),
            2
        )

        cv2.imshow("Traffic Agent - Emergency Priority", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
