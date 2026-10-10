from pathlib import Path

import cv2

from app.detection.detector import VehicleDetector
from app.tracking.tracker import VehicleTracker
from app.violation.database import save_violation
from app.violation.red_light import RedLightDetector


class TrafficVideoProcessor:

    def __init__(self):
        self.detector = VehicleDetector()
        self.tracker = VehicleTracker()

    def process(self, input_path, output_path):

        cap = cv2.VideoCapture(input_path)

        if not cap.isOpened():
            raise ValueError("Could not open video")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)

        if fps <= 0:
            fps = 30

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        out = cv2.VideoWriter(
            output_path,
            fourcc,
            fps,
            (width, height)
        )

        stop_line_y = 300
        signal_state = "RED"  # Simulated signal for initial testing
        violation_detector = RedLightDetector(stop_line_y)
        evidence_dir = Path("outputs/violations")
        evidence_dir.mkdir(parents=True, exist_ok=True)

        while True:

            ret, frame = cap.read()

            if not ret:
                break

            detections = self.detector.detect(frame)

            tracked = self.tracker.update(detections)

            for i in range(len(tracked.xyxy)):

                x1, y1, x2, y2 = map(
                    int,
                    tracked.xyxy[i]
                )

                track_id = (
                    int(tracked.tracker_id[i])
                    if tracked.tracker_id is not None
                    else -1
                )

                class_id = int(tracked.class_id[i])

                if track_id != -1 and violation_detector.check(
                    track_id,
                    y2,
                    signal_state
                ):
                    evidence_path = evidence_dir / (
                        f"red_light_id_{track_id}.jpg"
                    )
                    cv2.imwrite(str(evidence_path), frame)
                    save_violation(track_id, signal_state, evidence_path)
                    print(f"Red-light crossing detected: ID {track_id}")

                names = {
                    2: "car",
                    3: "motorcycle",
                    5: "bus",
                    7: "truck"
                }

                label = names.get(
                    class_id,
                    "vehicle"
                )

                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    (0, 255, 0),
                    2
                )

                cv2.putText(
                    frame,
                    f"{label} ID:{track_id}",
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2
                )

            cv2.line(
                frame,
                (0, stop_line_y),
                (frame.shape[1], stop_line_y),
                (0, 0, 255),
                2
            )

            out.write(frame)

            cv2.imshow(
                "Traffic Agent",
                frame
            )

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        cap.release()
        out.release()
        cv2.destroyAllWindows()
