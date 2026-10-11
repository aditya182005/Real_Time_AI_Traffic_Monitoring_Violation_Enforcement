from ultralytics import YOLO

DEFAULT_CONFIDENCE = 0.35


class VehicleDetector:

    def __init__(self, model_name="yolov8n.pt", confidence=DEFAULT_CONFIDENCE):
        # A bare model name lets Ultralytics download the weights on first
        # use (the *.pt files are git-ignored, so a fresh clone has none).
        self.model = YOLO(model_name)
        self.confidence = confidence

        self.vehicle_classes = {
            2: "car",
            3: "motorcycle",
            5: "bus",
            7: "truck"
        }

    def detect(self, frame, conf=None):

        # Filter by class inside the model call instead of post-filtering,
        # and use the same confidence as the other modules (speed/collision).
        # `conf` overrides the default per call (e.g. a UI slider) so one
        # loaded model can be reused.
        results = self.model(
            frame,
            classes=list(self.vehicle_classes),
            conf=self.confidence if conf is None else conf,
            verbose=False
        )[0]

        detections = []

        for box in results.boxes:

            class_id = int(box.cls[0])

            if class_id not in self.vehicle_classes:
                continue

            confidence = float(box.conf[0])

            x1, y1, x2, y2 = map(int, box.xyxy[0])

            detections.append({
                "class_id": class_id,
                "class_name": self.vehicle_classes[class_id],
                "confidence": confidence,
                "bbox": (x1, y1, x2, y2)
            })

        return detections
