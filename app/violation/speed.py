from datetime import datetime
from pathlib import Path

import cv2
import supervision as sv
from ultralytics import YOLO

from app.violation.violation_logger import log_violation

ROOT = Path(__file__).resolve().parents[2]

VIDEO_PATH = ROOT / "data" / "videos" / "traffic.mp4"
# Bare model name: Ultralytics downloads it on first use. The *.pt files are
# git-ignored, so a fresh clone does not contain the weights.
MODEL_PATH = "yolov8n.pt"
EVIDENCE_DIR = ROOT / "outputs" / "evidence"

# Adjust these to fit your video.
LINE_A_Y = 620
LINE_B_Y = 800
LINE_X1 = 250
LINE_X2 = 1450

DISTANCE_METERS = 10.0
SPEED_LIMIT_KMH = 40.0
CONFIDENCE = 0.35

VEHICLE_CLASSES = [2, 3, 5, 7]  # car, motorcycle, bus, truck


def main():
    if not VIDEO_PATH.exists():
        raise FileNotFoundError(f"Video not found: {VIDEO_PATH}")

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    model = YOLO(MODEL_PATH)
    tracker = sv.ByteTrack()

    cap = cv2.VideoCapture(str(VIDEO_PATH))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if not fps or fps <= 0:
        cap.release()
        raise ValueError("Could not read video FPS.")

    frame_number = 0

    # Track ID -> first line crossing frame.
    line_a_frames = {}
    previous_y = {}
    reported_tracks = set()

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        frame_number += 1

        result = model(
            frame,
            classes=VEHICLE_CLASSES,
            conf=CONFIDENCE,
            verbose=False
        )[0]

        detections = sv.Detections.from_ultralytics(result)
        detections = tracker.update_with_detections(detections)

        # Draw measurement lines.
        cv2.line(
            frame, (LINE_X1, LINE_A_Y),
            (LINE_X2, LINE_A_Y), (255, 255, 0), 2
        )
        cv2.line(
            frame, (LINE_X1, LINE_B_Y),
            (LINE_X2, LINE_B_Y), (0, 165, 255), 2
        )

        cv2.putText(
            frame, f"Limit: {SPEED_LIMIT_KMH} km/h",
            (20, 35), cv2.FONT_HERSHEY_SIMPLEX,
            0.8, (255, 255, 255), 2
        )

        if detections.tracker_id is not None:
            for i, box in enumerate(detections.xyxy):
                track_id = int(detections.tracker_id[i])
                x1, y1, x2, y2 = map(int, box)

                center_x = (x1 + x2) // 2
                bottom_y = y2
                old_y = previous_y.get(track_id)

                in_lane = LINE_X1 <= center_x <= LINE_X2

                if old_y is not None and in_lane:
                    # Record a downward crossing of Line A.
                    crossed_a = (
                        old_y < LINE_A_Y <= bottom_y
                    )

                    if crossed_a:
                        line_a_frames[track_id] = frame_number

                    # Calculate speed when the same vehicle
                    # subsequently crosses Line B.
                    crossed_b = (
                        old_y < LINE_B_Y <= bottom_y
                    )

                    if (
                        crossed_b
                        and track_id in line_a_frames
                        and track_id not in reported_tracks
                    ):
                        elapsed_frames = (
                            frame_number - line_a_frames[track_id]
                        )
                        elapsed_seconds = elapsed_frames / fps

                        if elapsed_seconds > 0:
                            speed_kmh = (
                                DISTANCE_METERS
                                / elapsed_seconds
                                * 3.6
                            )

                            print(
                                f"Track {track_id}: "
                                f"{speed_kmh:.2f} km/h"
                            )

                            if speed_kmh > SPEED_LIMIT_KMH:
                                timestamp = datetime.now().strftime(
                                    "%Y%m%d_%H%M%S"
                                )
                                evidence_path = (
                                    EVIDENCE_DIR
                                    / f"speed_{track_id}_{timestamp}.jpg"
                                )

                                cv2.rectangle(
                                    frame, (x1, y1), (x2, y2),
                                    (0, 0, 255), 2
                                )
                                cv2.putText(
                                    frame,
                                    f"OVERSPEED {speed_kmh:.1f} km/h",
                                    (x1, max(25, y1 - 10)),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.6, (0, 0, 255), 2
                                )

                                cv2.imwrite(
                                    str(evidence_path), frame
                                )
                                inserted = log_violation(
                                    event_key=f"speeding:{track_id}:{frame_number}",
                                    track_id=track_id,
                                    violation_type="speeding",
                                    evidence_path=str(evidence_path),
                                    speed=speed_kmh,
                                    speed_limit=SPEED_LIMIT_KMH,
                                )
                                print("Speeding record inserted:", inserted)
                                reported_tracks.add(track_id)

                previous_y[track_id] = bottom_y

                cv2.rectangle(
                    frame, (x1, y1), (x2, y2),
                    (0, 0, 255) if track_id in reported_tracks
                    else (0, 255, 0), 2
                )
                cv2.putText(
                    frame, f"ID {track_id}",
                    (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2
                )

        cv2.imshow("Traffic Agent - Speed Detection", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
