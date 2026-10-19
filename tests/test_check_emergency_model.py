import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import check_emergency_model as cm


def make(root):
    base = Path(root) / "ds"
    (base / "data.yaml").parent.mkdir(parents=True)
    (base / "data.yaml").write_text("test: images/test\n")
    (base / "images" / "test").mkdir(parents=True)
    (base / "labels" / "test").mkdir(parents=True)

    for name, label in (("neg1", ""), ("neg2", ""), ("pos", "0 .5 .5 .2 .2")):
        (base / "images" / "test" / f"{name}.jpg").write_bytes(b"x")
        (base / "labels" / "test" / f"{name}.txt").write_text(label)

    missing = base / "_review" / "missing_labels" / "train" / "images"
    missing.mkdir(parents=True)

    for i in range(4):
        (missing / f"m{i}.jpg").write_bytes(b"x")

    weights = Path(root) / "w.pt"
    weights.write_bytes(b"w")

    return base / "data.yaml", weights


class CheckTests(unittest.TestCase):

    def run_main(self, detections):
        with tempfile.TemporaryDirectory() as root:
            data, weights = make(root)
            out = io.StringIO()

            def factory(w, conf):
                return lambda images: [detections.get(p.stem, 0)
                                       for p in images]

            def evaluator(w, d, split="test"):
                return {"mAP50": 0.9, "precision": 0.9, "recall": 0.8,
                        "per_class": {"ambulance": {"mAP50": 0.9}}}

            with contextlib.redirect_stdout(out):
                code = cm.main(["--weights", str(weights), "--data",
                                str(data)], detector_factory=factory,
                               evaluator=evaluator)

        return code, out.getvalue()

    def test_only_empty_label_pictures_count_as_negatives(self):
        with tempfile.TemporaryDirectory() as root:
            data, _ = make(root)

            self.assertEqual(
                sorted(p.stem for p in cm.negative_images(data, "test")),
                ["neg1", "neg2"])
            self.assertEqual(len(cm.review_images(data)), 4)

    def test_report_gives_false_alarm_and_found_shares(self):
        code, out = self.run_main({"neg1": 2, "m0": 1, "m1": 3, "m2": 1})

        self.assertEqual(code, 0)
        self.assertIn("1 of 2 pictures with no emergency vehicle", out)
        self.assertIn("(50%)", out)
        self.assertIn("in 3 of 4 pictures", out)
        self.assertIn("mAP@0.5 0.90", out)

    def test_missing_files_are_clean_errors(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cm.main(["--weights", "nope.pt"]), 1)

        self.assertIn("Model not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()
