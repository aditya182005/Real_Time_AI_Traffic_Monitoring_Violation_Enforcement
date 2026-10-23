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


class ChunkTests(unittest.TestCase):
    def test_predicts_in_small_chunks_with_explicit_batch(self):
        calls = []

        class Model:
            def predict(self, source, **kwargs):
                calls.append((len(source), kwargs))
                return [object() for _ in source]

        results = list(cm.predict_in_chunks(Model(), [f"{i}.jpg" for i in range(40)], 0.3))

        self.assertEqual(len(results), 40)
        self.assertEqual([n for n, _ in calls], [16, 16, 8])
        self.assertTrue(all(k["batch"] == 4 and k["conf"] == 0.3 and not k.get("stream")
                            for _, k in calls))
        self.assertEqual(list(cm.predict_in_chunks(Model(), [], 0.3)), [])


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

    def run_negatives(self, per_picture, count=20):
        with tempfile.TemporaryDirectory() as root:
            data, weights = make(root)
            neg = Path(root) / "real"
            neg.mkdir()

            for i in range(count):
                (neg / f"r{i}.jpg").write_bytes(b"x")

            def classifier(w, conf):
                return lambda images: [per_picture.get(p.stem, [])
                                       for p in images]

            out = io.StringIO()

            with contextlib.redirect_stdout(out):
                cm.main(["--weights", str(weights), "--data", str(data),
                         "--negatives", str(neg)],
                        detector_factory=lambda w, c: (lambda im: [0] * len(im)),
                        evaluator=lambda w, d, split="test": {
                            "mAP50": 1, "precision": 1, "recall": 1},
                        classifier_factory=classifier)

        return out.getvalue()

    def test_real_negatives_name_the_wrong_class(self):
        out = self.run_negatives({"r0": [("fire_truck", 0.9)],
                                  "r1": [("fire_truck", 0.7),
                                         ("police_car", 0.5)],
                                  "r2": [("police_car", 0.6)]})

        self.assertIn("3 of 20 pictures with no emergency vehicle", out)
        self.assertIn("(15.0%)", out)
        self.assertIn("wrongly called fire_truck: 2", out)
        self.assertIn("wrongly called police_car: 1", out)
        self.assertIn("r0.jpg: fire_truck 0.90", out)
        self.assertIn("TOO MANY FALSE ALARMS", out)

    def test_real_negatives_pass_when_few_are_flagged(self):
        out = self.run_negatives({"r0": [("police_car", 0.4)]})

        self.assertIn("(5.0%)", out)
        self.assertIn("GOOD ENOUGH", out)

    def test_empty_negatives_folder_is_reported(self):
        self.assertIn("no pictures in", self.run_negatives({}, count=0))

    def test_missing_files_are_clean_errors(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cm.main(["--weights", "nope.pt"]), 1)

        self.assertIn("Model not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()
