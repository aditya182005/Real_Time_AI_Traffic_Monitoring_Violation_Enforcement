
import cv2
import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path

import supervision as sv
from ultralytics import YOLO
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

VIDEO_PATH = ROOT / "data" / "videos" / "traffic.mp4"
MODEL_PATH = ROOT / "yolov8n.pt"
DB_PATH = ROOT / "traffic_agent.db"
OUTPUT_DIR = ROOT / "outputs" / "collisions"

CONFIDENCE = 0.35
PERSISTENCE_FRAMES = 3
IOU_THRESHOLD = 0.15
VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck


def setup_database():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collision_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id_1 INTEGER NOT NULL,
                track_id_2 INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                evidence_path TEXT NOT NULL
            )
        """)


def calculate_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    x1 = max(ax1, bx1)
    y1 = max(ay1, by1)
    x2 = min(ax2, bx2)
    y2 = min(ay2, by2)

    intersection = max(0, x2 - x1) * max(0, y2 - y1)

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)

    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


def send_sms(message):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    to_number = os.getenv("ALERT_TO_PHONE")

    if not all([account_sid, auth_token, from_number, to_number]):
        print("Twilio not configured. SMS skipped.")
        return

    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        print("Twilio SMS submitted.")
    except Exception as exc:
        print(f"Twilio SMS failed: {exc}")


def main():
    if not VIDEO_PATH.exists():
        raise FileNotFoundError(f"Video not found: {VIDEO_PATH}")

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model not found: {MODEL_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_database()

    model = YOLO(str(MODEL_PATH))
    tracker = sv.ByteTrack()
    cap = cv2.VideoCapture(str(VIDEO_PATH))

    # Pair -> number of consecutive overlapping frames.
    overlap_counts = {}
    reported_pairs = set()
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

        active_pairs = set()
        collision_pairs = []

        for i in range(len(vehicles)):
            id_a, box_a = vehicles[i]

            for j in range(i + 1, len(vehicles)):
                id_b, box_b = vehicles[j]

                if id_a == id_b:
                    continue

                pair = tuple(sorted((id_a, id_b)))
                iou = calculate_iou(box_a, box_b)

                if iou >= IOU_THRESHOLD:
                    active_pairs.add(pair)
                    overlap_counts[pair] = (
                        overlap_counts.get(pair, 0) + 1
                    )

                    if overlap_counts[pair] >= PERSISTENCE_FRAMES:
                        collision_pairs.append((pair, box_a, box_b))
                # Non-overlapping pairs are reset below.

        # Reset consecutive counts when overlap stops.
        for pair in list(overlap_counts):
            if pair not in active_pairs:
                del overlap_counts[pair]

        for pair, box_a, box_b in collision_pairs:
            if pair in reported_pairs:
                continue

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

            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    INSERT INTO collision_events (
                        track_id_1,
                        track_id_2,
                        event_type,
                        timestamp,
                        evidence_path
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    id_a,
                    id_b,
                    "possible_collision",
                    timestamp,
                    str(evidence_path)
                ))

            reported_pairs.add(pair)

            message = (
                f"Traffic Agent: possible collision detected "
                f"between vehicle tracks {id_a} and {id_b}. "
                f"Please verify the incident."
            )

            print(message)
            send_sms(message)

        cv2.imshow("Traffic Agent - Collision Monitoring", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

