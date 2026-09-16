import cv2

from app.detection.detector import VehicleDetector
from app.tracking.tracker import VehicleTracker


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