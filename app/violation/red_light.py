class RedLightDetector:
    """Detects a vehicle crossing the stop line while the signal is red.

    This class only decides *whether* a crossing happened. Saving evidence
    and writing the database record is the caller's job, so the evidence
    image can be saved with the final annotated frame and the record can
    carry its path (previously the record was written first with an empty
    evidence path, and a second legacy table was written as well).
    """

    def __init__(self, stop_line_y):
        self.stop_line_y = stop_line_y
        self.previous_y = {}
        self.reported_ids = set()

    def check(self, track_id, vehicle_y, signal_state):
        if track_id is None:
            return False

        previous_y = self.previous_y.get(track_id)
        self.previous_y[track_id] = vehicle_y

        if track_id in self.reported_ids:
            return False

        crossed_line = (
            previous_y is not None
            and previous_y < self.stop_line_y
            and vehicle_y >= self.stop_line_y
        )

        if crossed_line and signal_state == "RED":
            self.reported_ids.add(track_id)
            return True

        return False
