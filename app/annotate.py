"""Small OpenCV drawing helpers shared by the video and image pipelines."""

import cv2

# BGR colours
VEHICLE = (80, 200, 60)
VIOLATION = (60, 60, 240)
EMERGENCY = (0, 150, 255)
WHITE = (255, 255, 255)


def draw_box(frame, bbox, label, colour, thickness=2):
    x1, y1, x2, y2 = map(int, bbox)

    cv2.rectangle(frame, (x1, y1), (x2, y2), colour, thickness)

    if label:
        (w, h), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
        )
        top = max(0, y1 - h - baseline - 4)

        cv2.rectangle(
            frame, (x1, top), (x1 + w + 6, top + h + baseline + 4),
            colour, -1
        )
        cv2.putText(
            frame, label, (x1 + 3, top + h + 1),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA
        )


def draw_banner(frame, text, colour, origin=(15, 15)):
    """Filled label in the top-left corner (signal state, alerts)."""

    (w, h), baseline = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
    )
    x, y = origin

    cv2.rectangle(
        frame, (x, y), (x + w + 16, y + h + baseline + 12), colour, -1
    )
    cv2.putText(
        frame, text, (x + 8, y + h + 5),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, WHITE, 2, cv2.LINE_AA
    )

    return y + h + baseline + 20  # next free y position


def crop_with_margin(frame, bbox, margin=0.15):
    """Crop a vehicle out of a frame, with a little context around it."""

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = map(int, bbox)

    pad_x = int((x2 - x1) * margin)
    pad_y = int((y2 - y1) * margin)

    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(width, x2 + pad_x)
    y2 = min(height, y2 + pad_y)

    return frame[y1:y2, x1:x2].copy()


def draw_calibration(frame, stop_line_y, speed_lines=None, lane=None):
    """Draw the lines a user is positioning, on a copy of ``frame``.

    stop_line_y: pixel row of the stop line (red).
    speed_lines: ``(line_a_y, line_b_y)`` pixel rows (amber), or None.
    lane:        ``(x_min, x_max)`` pixel columns to shade (blue), or None.
    """

    preview = frame.copy()
    height, width = preview.shape[:2]

    if lane is not None:
        shade = preview.copy()
        cv2.rectangle(shade, (int(lane[0]), 0), (int(lane[1]), height),
                      (154, 76, 15), -1)
        cv2.addWeighted(shade, 0.22, preview, 0.78, 0, preview)

    cv2.line(preview, (0, stop_line_y), (width, stop_line_y), VIOLATION, 3)
    cv2.putText(preview, "Stop line", (12, max(22, stop_line_y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, VIOLATION, 2, cv2.LINE_AA)

    if speed_lines is not None:
        amber = (0, 170, 255)

        for name, line_y in zip(("A", "B"), speed_lines):
            cv2.line(preview, (0, int(line_y)), (width, int(line_y)), amber, 2)
            cv2.putText(preview, f"Speed line {name}",
                        (12, max(22, int(line_y) - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, amber, 2, cv2.LINE_AA)

    return preview
