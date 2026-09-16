from ultralytics import YOLO


class VehicleDetector:

    def __init__(self):
        self.model = YOLO("yolov8n.pt")

        self.vehicle_classes = {
            2: "car",
            3: "motorcycle",
            5: "bus",
            7: "truck"
        }

    def detect(self, frame):

        results = self.model(frame, verbose=False)[0]

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