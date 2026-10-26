from pathlib import Path

from app.violation.helmet import HELMET, NO_HELMET

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = ROOT / "models" / "helmet.pt"
DEFAULT_CONFIDENCE = 0.4



def normalise(name):
    """Map a model's class name to ``helmet`` / ``no_helmet`` (or None)."""

    text = str(name).lower().replace(" ", "_")

    if "helmet" not in text and text not in ("head", "no_head"):
        return None

    if text in ("head", "bare_head") or any(
            text.startswith(p) for p in ("no_", "no-", "without", "nohelmet")):
        return NO_HELMET

    return HELMET


class HelmetDetector:
    """Finds heads with and without helmets using your own trained weights.

    There is no helmet model in this repository, and none is claimed to be
    accurate: train one on a helmet dataset (``docs/TRAINING.md``), put it at
    ``models/helmet.pt`` and measure it on your own footage first.
    """

    def __init__(self, model_path=DEFAULT_MODEL_PATH, confidence=DEFAULT_CONFIDENCE):
        model_path = Path(model_path)

        if not model_path.exists():
            raise FileNotFoundError(f"Helmet model not found: {model_path}")

        from ultralytics import YOLO

        self.model = YOLO(str(model_path))
        self.confidence = confidence
        self.classes = {int(i): normalise(n)
                        for i, n in dict(self.model.names).items()}

        if not any(self.classes.values()):
            raise ValueError("The helmet model has no class named like "
                             "'helmet' or 'no helmet'.")

    @staticmethod
    def available(model_path=DEFAULT_MODEL_PATH):
        return Path(model_path).exists()

    def detect(self, frame, conf=None):
        results = self.model(frame, conf=self.confidence if conf is None
                             else conf, verbose=False)[0]
        found = []

        for box in results.boxes:
            name = self.classes.get(int(box.cls[0]))

            if name is None:
                continue

            found.append({
                "class_name": name,
                "confidence": float(box.conf[0]),
                "bbox": tuple(map(int, box.xyxy[0])),
            })

        return found
