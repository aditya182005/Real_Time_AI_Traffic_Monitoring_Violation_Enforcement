import json
import unittest
from pathlib import Path

import evaluate

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"
VIDEOS = ROOT / "data" / "videos"


class SampleDataTests(unittest.TestCase):

    def test_sample_pictures_are_all_there(self):
        names = {p.name for p in SAMPLES.glob("*.jpg")}
        expected = {f"{kind}_{n}.jpg"
                    for kind, count in (("ambulance", 3), ("fire_truck", 3),
                                        ("police_car", 3), ("ordinary", 6))
                    for n in range(1, count + 1)}

        self.assertEqual(names, expected)

    def test_boxes_file_covers_every_picture(self):
        boxes = json.loads((SAMPLES / "boxes.json").read_text())

        self.assertEqual(set(boxes), {p.name for p in SAMPLES.glob("*.jpg")})

        for name, box in boxes.items():
            if name.startswith("ordinary"):
                self.assertIsNone(box)
            else:
                self.assertEqual(len(box), 4, name)

    def test_attribution_is_included(self):
        text = (SAMPLES / "README.md").read_text()

        self.assertIn("CC BY 4.0", text)
        self.assertIn("roboflow.com", text)

    def test_truth_file_has_each_check_once(self):
        events = evaluate.load_truth(VIDEOS / "demo_all_checks_truth.csv")

        self.assertEqual(sorted(kind for kind, _ in events),
                         ["collision", "red_light", "speeding", "wrong_way"])

    def test_demo_video_is_readable_and_the_right_length(self):
        try:
            import cv2
        except ImportError:
            self.skipTest("OpenCV not installed")

        capture = cv2.VideoCapture(str(VIDEOS / "demo_all_checks.mp4"))

        if not capture.isOpened():
            self.skipTest("this OpenCV build cannot read mp4v video")

        self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), 900)
        self.assertEqual(int(capture.get(cv2.CAP_PROP_FPS)), 30)
        capture.release()


if __name__ == "__main__":
    unittest.main()
