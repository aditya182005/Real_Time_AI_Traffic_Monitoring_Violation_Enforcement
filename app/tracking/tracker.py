import numpy as np
import supervision as sv


class VehicleTracker:

    def __init__(self):
        self.tracker = sv.ByteTrack()

    def update(self, detections):
        """Update ByteTrack and always return an ``sv.Detections``.

        Empty frames are still passed to ByteTrack so lost tracks age out
        correctly, and callers can safely use ``.xyxy`` / ``.tracker_id``
        without special-casing a plain list.
        """

        if not detections:
            return self.tracker.update_with_detections(
                sv.Detections.empty()
            )

        xyxy = []
        confidence = []
        class_id = []

        for detection in detections:

            xyxy.append(detection["bbox"])
            confidence.append(detection["confidence"])
            class_id.append(detection["class_id"])

        tracked = sv.Detections(
            xyxy=np.array(xyxy, dtype=float),
            confidence=np.array(confidence, dtype=float),
            class_id=np.array(class_id, dtype=int)
        )

        return self.tracker.update_with_detections(tracked)
