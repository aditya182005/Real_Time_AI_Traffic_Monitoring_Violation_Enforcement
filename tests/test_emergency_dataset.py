import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "emergency_vehicle"
SPLITS = ("train", "val", "test")


@unittest.skipUnless(ROOT.is_dir(), "dataset not present")
class EmergencyDatasetTests(unittest.TestCase):

    def test_every_image_has_a_label_file_and_the_reverse(self):
        for split in SPLITS:
            images = {p.stem for p in (ROOT / "images" / split).iterdir()}
            labels = {p.stem for p in (ROOT / "labels" / split).glob("*.txt")}

            self.assertEqual(images, labels, split)

    def test_every_label_row_is_a_valid_box(self):
        for split in SPLITS:
            for path in (ROOT / "labels" / split).glob("*.txt"):
                for number, line in enumerate(
                        path.read_text().splitlines(), 1):
                    if not line.strip():
                        continue

                    parts = line.split()
                    where = f"{path.name}:{number}"

                    self.assertEqual(len(parts), 5, where)
                    self.assertIn(parts[0], {"0", "1", "2"}, where)

                    x, y, w, h = map(float, parts[1:])
                    self.assertTrue(
                        0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1
                        and 0 < h <= 1, where)

    def test_images_with_vehicles_missing_labels_are_kept_out_of_training(self):
        # They sit in _review/ until someone labels them.
        self.assertTrue((ROOT / "_review" / "missing_labels").is_dir())
        self.assertFalse(list((ROOT / "images").glob("*/_review*")))

    def test_each_class_is_in_every_split(self):
        for split in SPLITS:
            classes = set()

            for path in (ROOT / "labels" / split).glob("*.txt"):
                classes |= {l.split()[0] for l in path.read_text().splitlines()
                            if l.strip()}

            self.assertEqual(classes, {"0", "1", "2"}, split)


if __name__ == "__main__":
    unittest.main()
