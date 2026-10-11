from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = ROOT / "models" / "emergency_vehicle.pt"
DEFAULT_CONFIDENCE = 0.65


class EmergencyDetector:
    """Detects ambulances, fire trucks and police cars with the custom model.

    The weights come from ``train_emergency.py`` and are not stored in git:
    copy ``runs/detect/emergency_vehicle/weights/best.pt`` to
    ``models/emergency_vehicle.pt``.
    """

    def __init__(self, model_path=DEFAULT_MODEL_PATH,
                 confidence=DEFAULT_CONFIDENCE):
        model_path = Path(model_path)

        if not model_path.exists():
            raise FileNotFoundError(
                f"Emergency-vehicle model not found: {model_path}"
            )

        from ultralytics import YOLO

        self.model = YOLO(str(model_path))
        self.confidence = confidence

    @staticmethod
    def available(model_path=DEFAULT_MODEL_PATH):
        return Path(model_path).exists()

    def detect(self, frame, conf=None):
        results = self.model(
            frame,
            conf=self.confidence if conf is None else conf,
            imgsz=640,
            verbose=False
        )[0]

        detections = []

        for box in results.boxes:
            class_id = int(box.cls[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            detections.append({
                "class_id": class_id,
                "class_name": self.model.names[class_id],
                "confidence": float(box.conf[0]),
                "bbox": (x1, y1, x2, y2)
            })

        return detections
