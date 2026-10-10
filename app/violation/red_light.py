
class RedLightDetector:
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
