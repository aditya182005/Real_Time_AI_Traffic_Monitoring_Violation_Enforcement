import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

import extract_frames as ef
import fetch_coco_negatives as fc


def coco(images):
    """images: {id: (category ids, caption)} -> (instances, captions)."""

    inst = {"images": [], "annotations": []}
    caps = {"annotations": []}

    for image_id, (cats, caption) in images.items():
        inst["images"].append({"id": image_id, "file_name": f"{image_id}.jpg",
                               "width": 100, "height": 100})
        caps["annotations"].append({"image_id": image_id, "caption": caption})

        for cat in cats:
            inst["annotations"].append({"image_id": image_id,
                                        "category_id": cat, "area": 2000,
                                        "iscrowd": 0})

    return inst, caps


class CocoSelectionTests(unittest.TestCase):
    def test_annotation_and_image_names_follow_the_split(self):
        self.assertEqual(fc.annotation_names("train"),
                         ("instances_train2017.json", "captions_train2017.json"))
        self.assertIn("/train2017/", fc.IMAGE_URL.format(split="train", name="x"))
        self.assertIn("/val2017/", fc.IMAGE_URL.format(split="val", name="x"))

    def test_emergency_captions_are_excluded(self):
        inst, caps = coco({
            1: ([3], "a red car on a street"),
            2: ([8], "a fire truck parked outside"),
            3: ([3], "A police car with its siren on"),
            4: ([8], "an ambulance in traffic"),
            5: ([6], "a bus at a stop")})

        self.assertEqual(fc.select(inst, caps, 10), ["1.jpg", "5.jpg"])

    def test_small_or_missing_vehicles_are_skipped(self):
        inst, caps = coco({1: ([3], "a car"), 2: ([], "a dog"),
                           3: ([3], "a tiny car")})
        inst["annotations"][-1]["area"] = 10        # image 3: nearly invisible

        self.assertEqual(fc.select(inst, caps, 10), ["1.jpg"])

    def test_trucks_and_buses_make_up_about_half(self):
        inst, caps = coco({**{i: ([3], "a car") for i in range(1, 21)},
                           **{i: ([8], "a truck") for i in range(21, 41)}})
        chosen = fc.select(inst, caps, 10)
        heavy = [n for n in chosen if int(n.split(".")[0]) > 20]

        self.assertEqual(len(chosen), 10)
        self.assertEqual(len(heavy), 5)

    def test_tops_up_when_one_kind_runs_out(self):
        inst, caps = coco({i: ([3], "a car") for i in range(1, 6)})

        self.assertEqual(len(fc.select(inst, caps, 4)), 4)

    def test_selection_is_repeatable(self):
        inst, caps = coco({i: ([3], "a car") for i in range(1, 30)})

        self.assertEqual(fc.select(inst, caps, 8, seed=1),
                         fc.select(inst, caps, 8, seed=1))


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class ExtractFramesTests(unittest.TestCase):
    def test_saves_one_picture_per_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            writer = cv2.VideoWriter(
                str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))

            if not writer.isOpened():
                self.skipTest("cannot write mp4v")

            for _ in range(50):                       # 5 seconds at 10 fps
                writer.write(np.zeros((48, 64, 3), np.uint8))

            writer.release()
            names = ef.extract(video, Path(tmp) / "out", every_seconds=2)

            self.assertEqual(len(names), 3)           # 0 s, 2 s, 4 s
            self.assertTrue((Path(tmp) / "out" / names[0]).is_file())
            self.assertEqual(
                ef.main(["--video", str(tmp), "--output",
                         str(Path(tmp) / "o2"), "--max-frames", "1"]), 0)

    def test_bad_video_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ef.extract(Path(tmp) / "none.mp4", Path(tmp) / "o")


if __name__ == "__main__":
    unittest.main()
