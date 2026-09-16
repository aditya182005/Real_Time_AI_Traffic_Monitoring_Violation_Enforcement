import numpy as np  
import supervision as sv

class VehicleTracker:

    def __init__(self):
        self.tracker = sv.ByteTrack()

    def update(self, detections):

        if not detections:
            return []

        xyxy = []
        confidence = []
        class_id = []

        for detection in detections:

            xyxy.append(detection["bbox"])
            confidence.append(detection["confidence"])
            class_id.append(detection["class_id"])

        tracked = sv.Detections(
            xyxy=np.array(xyxy),
            confidence=np.array(confidence),
            class_id=np.array(class_id)
        )

        tracked = self.tracker.update_with_detections(tracked)

        return tracked