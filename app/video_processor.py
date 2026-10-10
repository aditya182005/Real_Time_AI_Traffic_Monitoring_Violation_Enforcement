from pathlib import Path

import cv2

from app.violation.red_light import RedLightDetector
from app.violation.violation_logger import log_violation

ROOT = Path(__file__).resolve().parents[1]

VEHICLE_NAMES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck"
}


class TrafficVideoProcessor:

    def __init__(
        self,
        detector=None,
        tracker=None,
        stop_line_y=300,
        signal_state="RED",  # Simulated signal for testing
        evidence_dir=None,
    ):
        # Imported lazily so the heavy YOLO / supervision stack is only
        # loaded when real components are needed (tests inject fakes).
        if detector is None:
            from app.detection.detector import VehicleDetector
            detector = VehicleDetector()

        if tracker is None:
            from app.tracking.tracker import VehicleTracker
            tracker = VehicleTracker()

        self.detector = detector
        self.tracker = tracker
        self.stop_line_y = stop_line_y
        self.signal_state = signal_state
        self.evidence_dir = (
            Path(evidence_dir)
            if evidence_dir
            else ROOT / "outputs" / "violations"
        )

    def process(self, input_path, output_path, show=True):

        cap = cv2.VideoCapture(str(input_path))

        if not cap.isOpened():
            raise ValueError(f"Could not open video: {input_path}")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)

        if not fps or fps <= 0:
            fps = 30

        # VideoWriter fails silently when the folder is missing.
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        out = cv2.VideoWriter(
            str(output_path),
            fourcc,
            fps,
            (width, height)
        )

        if not out.isOpened():
            cap.release()
            raise ValueError(f"Could not open output video: {output_path}")

        violation_detector = RedLightDetector(self.stop_line_y)
        frame_number = 0

        try:
            while True:

                ret, frame = cap.read()

                if not ret:
                    break

                frame_number += 1

                detections = self.detector.detect(frame)

                tracked = self.tracker.update(detections)

                violations = []

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

                    is_violation = (
                        track_id != -1
                        and violation_detector.check(
                            track_id,
                            y2,
                            self.signal_state
                        )
                    )

                    if is_violation:
                        violations.append(track_id)

                    label = VEHICLE_NAMES.get(class_id, "vehicle")
                    colour = (0, 0, 255) if is_violation else (0, 255, 0)

                    cv2.rectangle(
                        frame,
                        (x1, y1),
                        (x2, y2),
                        colour,
                        2
                    )

                    cv2.putText(
                        frame,
                        f"{label} ID:{track_id}",
                        (x1, max(20, y1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        colour,
                        2
                    )

                cv2.line(
                    frame,
                    (0, self.stop_line_y),
                    (frame.shape[1], self.stop_line_y),
                    (0, 0, 255),
                    2
                )

                cv2.putText(
                    frame,
                    f"Signal: {self.signal_state} (simulated)",
                    (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2
                )

                # Save evidence AFTER annotating so the image shows the boxes
                # and stop line, then log once with the evidence path.
                for track_id in violations:
                    evidence_path = self.evidence_dir / (
                        f"red_light_id_{track_id}_frame_{frame_number}.jpg"
                    )
                    cv2.imwrite(str(evidence_path), frame)

                    inserted = log_violation(
                        event_key=f"red_light:{track_id}:{frame_number}",
                        track_id=track_id,
                        violation_type="red_light",
                        evidence_path=evidence_path,
                        signal_state=self.signal_state,
                    )

                    print(
                        f"Red-light crossing detected: ID {track_id} "
                        f"(record inserted: {inserted})"
                    )

                out.write(frame)

                if show:
                    cv2.imshow("Traffic Agent", frame)

                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

        finally:
            cap.release()
            out.release()

            if show:
                cv2.destroyAllWindows()
