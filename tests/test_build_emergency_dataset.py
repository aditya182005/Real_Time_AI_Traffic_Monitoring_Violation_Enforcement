import tempfile
import unittest
from pathlib import Path

import build_emergency_dataset as bd


def make_source(root, name, names, photos, layout="roboflow"):
    """photos: {stem: [label lines]}; every image gets unique bytes."""

    base = Path(root) / name
    base.mkdir(parents=True)
    (base / "data.yaml").write_text(
        "train: ../train/images\nnames: " + str(names) + "\n")

    for i, (stem, lines) in enumerate(photos.items()):
        split = "train" if i % 2 == 0 else "valid"
        (base / split / "images").mkdir(parents=True, exist_ok=True)
        (base / split / "labels").mkdir(parents=True, exist_ok=True)
        (base / split / "images" / f"{stem}.jpg").write_bytes(
            f"{name}{stem}".encode())
        (base / split / "labels" / f"{stem}.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""))

    return base


BOX = "0.5 0.5 0.4 0.4"


class NameTests(unittest.TestCase):

    def test_names_map_by_keyword(self):
        for name, expected in (
                ("ambulance_on", 0), ("Ambulance", 0), ("firetruck_off", 1),
                ("Fire_Truck", 1), ("police-car", 2), ("Police", 2),
                ("car", "ordinary"), ("autorickshaw", "ordinary"),
                ("Siren_On", None), ("2", None)):
            self.assertEqual(bd.class_for_name(name), expected, name)

    def test_names_are_read_from_inline_list_and_block_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.yaml"
            a.write_text("names: ['x', 'y z']\nnc: 2\n")
            b = Path(tmp) / "b.yaml"
            b.write_text("names:\n  0: x\n  1: y\n")

            c = Path(tmp) / "c.yaml"
            c.write_text("train: a\nnames:\n- x\n- y\nnc: 2\n")
            d = Path(tmp) / "d.yaml"
            d.write_text("names:\n  - x\n  - y\nroboflow:\n  a: b\n")

            self.assertEqual(bd.read_names(c), ["x", "y"])
            self.assertEqual(bd.read_names(d), ["x", "y"])
            self.assertEqual(bd.read_names(a), ["x", "y z"])
            self.assertEqual(bd.read_names(b), ["x", "y"])

    def test_photo_key_groups_roboflow_augmentations(self):
        self.assertEqual(bd.photo_key("12_jpg.rf.abc123"), "12")
        self.assertEqual(bd.photo_key("12_jpg.rf.zzz999"), "12")
        self.assertEqual(bd.photo_key("plain"), "plain")

    def test_polygon_becomes_a_box_and_tiny_boxes_are_dropped(self):
        box = bd.to_box([0.2, 0.2, 0.6, 0.2, 0.6, 0.8, 0.2, 0.8])

        self.assertAlmostEqual(box[2], 0.4)
        self.assertIsNone(bd.clean_box([0.5, 0.5, 0.001, 0.3]))

    def test_source_can_force_a_class(self):
        self.assertEqual(bd.parse_source("data/x:fire_truck"),
                         (Path("data/x"), 1))
        self.assertEqual(bd.parse_source("data/x"), (Path("data/x"), None))


class BuildTests(unittest.TestCase):

    def build(self, tmp, sources, **kw):
        out = Path(tmp) / "out"
        report = bd.build([str(s) for s in sources], out, **kw)

        return out, report

    def test_classes_are_remapped_and_others_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = make_source(tmp, "a", ["car", "ambulance", "Police"], {
                "p1": [f"1 {BOX}", f"0 0.1 0.1 0.1 0.1"],
                "p2": [f"2 {BOX}"],
            })

            out, report = self.build(tmp, [src])
            labels = "".join(p.read_text()
                             for p in (out / "labels").rglob("*.txt"))

            self.assertIn("0 0.500000", labels)   # ambulance -> 0
            self.assertIn("2 0.500000", labels)   # police -> 2
            self.assertNotIn("1 0.1", labels)     # nothing becomes class 1

    def test_ordinary_only_images_are_negatives_unknown_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = make_source(tmp, "a", ["car", "Siren_On", "ambulance"], {
                "neg": [f"0 {BOX}"],
                "unsure": [f"1 {BOX}"],
                "empty": [],
                "pos": [f"2 {BOX}"],
            })

            _, report = self.build(tmp, [src])
            total = sum(s["images"] for s in report["splits"].values())
            negatives = sum(s["negatives"] for s in report["splits"].values())

            self.assertEqual(total, 2)            # neg + pos
            self.assertEqual(negatives, 1)
            self.assertEqual(report["sources"]["s0"]["dropped_unsure"], 2)

    def test_a_broken_source_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = make_source(tmp, "a", ["ambulance"], {"x": [f"0 {BOX}"]})
            bad = Path(tmp) / "bad"
            bad.mkdir()
            (bad / "data.yaml").write_text("nothing: here\n")

            _, report = self.build(tmp, [good, bad])

            self.assertIn("error", report["sources"]["s1"])
            self.assertEqual(
                sum(s["images"] for s in report["splits"].values()), 1)

    def test_duplicates_across_sources_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = make_source(tmp, "a", ["ambulance"], {"x": [f"0 {BOX}"]})
            b = make_source(tmp, "b", ["ambulance"], {"y": [f"0 {BOX}"]})
            # same bytes as a's image
            (b / "train" / "images" / "y.jpg").write_bytes(b"ax")

            _, report = self.build(tmp, [a, b])

            self.assertEqual(report["duplicates_removed"], 1)

    def test_augmented_copies_of_one_photo_stay_in_one_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            photos = {}

            for n in range(30):
                for aug in "abc":
                    photos[f"{n}_jpg.rf.{aug}{n}"] = [f"{n % 3} {BOX}"]

            src = make_source(tmp, "a", ["ambulance", "fire truck", "police"],
                              photos)
            out, _ = self.build(tmp, [src])
            seen = {}

            for split in bd.SPLITS:
                for image in (out / "images" / split).iterdir():
                    photo = image.stem.split("__")[1].split("_jpg")[0]
                    self.assertEqual(seen.setdefault(photo, split), split)

            self.assertEqual(len(seen), 30)

    def test_forced_class_overrides_meaningless_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = make_source(tmp, "a", ["2"], {"x": [f"0 {BOX}"]})
            out, report = self.build(tmp, [f"{src}:fire_truck"])
            total = sum(s["boxes"]["fire_truck"]
                        for s in report["splits"].values())

            self.assertEqual(total, 1)

    def test_negatives_folder_adds_empty_label_pictures(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = make_source(tmp, "a", ["ambulance"],
                              {f"p{i}": [f"0 {BOX}"] for i in range(20)})
            neg = Path(tmp) / "neg" / "nested"
            neg.mkdir(parents=True)

            for i in range(30):
                (neg / f"car{i}.jpg").write_bytes(f"neg{i}".encode())

            (neg / "notes.txt").write_text("not a picture")
            out, report = self.build(
                tmp, [src], negatives=[Path(tmp) / "neg"])

            total = sum(s["negatives"] for s in report["splits"].values())
            labels = [p for p in (out / "labels").rglob("*.txt")
                      if "neg_" in p.name]

            self.assertEqual(total, 30)
            self.assertEqual(len(labels), 30)
            self.assertTrue(all(not p.read_text() for p in labels))
            self.assertEqual(report["sources"]["negatives"]["added"], 30)

    def test_negatives_can_be_capped_and_missing_folder_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = make_source(tmp, "a", ["ambulance"],
                              {f"p{i}": [f"0 {BOX}"] for i in range(10)})
            neg = Path(tmp) / "neg"
            neg.mkdir()

            for i in range(30):
                (neg / f"c{i}.jpg").write_bytes(f"n{i}".encode())

            _, report = self.build(
                tmp, [src], negatives=[neg, Path(tmp) / "absent"],
                max_negatives=5)

            self.assertEqual(sum(s["negatives"]
                                 for s in report["splits"].values()), 5)

    def test_negatives_alone_with_a_source_cli(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(bd.main(["--output", str(Path(tmp) / "o")]), 1)

    def test_too_few_negatives_is_warned_about(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            src = make_source(tmp, "a", ["ambulance"],
                              {f"p{i}": [f"0 {BOX}"] for i in range(40)})
            _, report = self.build(tmp, [src])
            out = io.StringIO()

            with contextlib.redirect_stdout(out):
                bd.print_report(report)

        self.assertIn("flags ordinary cars, trucks and vans", out.getvalue())

    def test_output_is_a_valid_dataset_for_training(self):
        import train_emergency as te

        with tempfile.TemporaryDirectory() as tmp:
            photos = {f"p{i}": [f"{i % 3} {BOX}"] for i in range(40)}
            src = make_source(tmp, "a", ["ambulance", "firetruck", "police"],
                              photos)
            out, _ = self.build(tmp, [src])

            counts = te.check_dataset(out / "data.yaml")

            self.assertGreater(counts["train"], 0)
            self.assertGreater(counts["val"], 0)
            self.assertTrue(te.has_split(out / "data.yaml", "test"))
            self.assertIn("2: police_car",
                          (out / "data.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
