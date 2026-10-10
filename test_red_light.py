
from app.violation.red_light import RedLightDetector

detector = RedLightDetector(stop_line_y=300)

tests = [
    (1, 250, "RED"),
    (1, 320, "RED"),
    (1, 350, "RED"),
    (2, 250, "GREEN"),
    (2, 320, "GREEN"),
    (3, 250, "RED"),
    (3, 320, "GREEN"),
]

for track_id, y, signal in tests:
    violation = detector.check(track_id, y, signal)
    print(
        f"ID={track_id}, y={y}, signal={signal}, "
        f"violation={violation}"
    )
