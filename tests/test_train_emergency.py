import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import train_emergency as te


def make_dataset(root, train=3, val=2, labels=True):
    base = Path(root) / "emergency_vehicle"
    (base / "data.yaml").parent.mkdir(parents=True, exist_ok=True)
    (base / "data.yaml").write_text("train: images/train\nval: images/val\n")

    for split, count in (("train", train), ("val", val)):
        (base / "images" / split).mkdir(parents=True)

        if labels:
            (base / "labels" / split).mkdir(parents=True)

        for i in range(count):
            (base / "images" / split / f"{i}.jpg").write_bytes(b"x")

    return base / "data.yaml"


def make_run(root, files=("best.pt",)):
    weights = Path(root) / "run" / "weights"
    weights.mkdir(parents=True)

    for name in files:
        (weights / name).write_bytes(name.encode())

    return weights.parent


class DatasetTests(unittest.TestCase):

    def test_counts_images(self):
        with tempfile.TemporaryDirectory() as root:
            counts = te.check_dataset(make_dataset(root, train=5, val=2))

        self.assertEqual(counts, {"train": 5, "val": 2})

    def test_missing_yaml_missing_labels_and_empty_split_are_clear_errors(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(FileNotFoundError, "not found"):
                te.check_dataset(Path(root) / "nope.yaml")

        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(FileNotFoundError, "labels"):
                te.check_dataset(make_dataset(root, labels=False))

        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "No images"):
                te.check_dataset(make_dataset(root, val=0))

    def test_the_real_dataset_in_the_repo_is_complete(self):
        counts = te.check_dataset()

        self.assertGreater(counts["train"], 100)
        self.assertGreater(counts["val"], 10)


class WeightsTests(unittest.TestCase):

    def test_best_is_preferred_over_last(self):
        with tempfile.TemporaryDirectory() as root:
            run = make_run(root, ("last.pt", "best.pt"))

            self.assertEqual(te.find_best_weights(run).name, "best.pt")

    def test_last_is_used_when_there_is_no_best(self):
        with tempfile.TemporaryDirectory() as root:
            run = make_run(root, ("last.pt",))

            self.assertEqual(te.find_best_weights(run).name, "last.pt")

    def test_no_weights_is_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):
                te.find_best_weights(Path(root))

    def test_install_creates_the_models_folder(self):
        with tempfile.TemporaryDirectory() as root:
            source = make_run(root) / "weights" / "best.pt"
            target = Path(root) / "models" / "emergency_vehicle.pt"

            te.install_weights(source, target)

            self.assertEqual(target.read_bytes(), b"best.pt")


class MainTests(unittest.TestCase):

    def run_main(self, root, trainer, *extra):
        data = make_dataset(root)
        output = Path(root) / "models" / "emergency_vehicle.pt"
        out, err = io.StringIO(), io.StringIO()

        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = te.main(["--data", str(data), "--output", str(output),
                            *extra], trainer=trainer)

        return code, output, out.getvalue(), err.getvalue()

    def test_successful_training_installs_the_weights(self):
        calls = {}

        def trainer(base, **options):
            calls.update(base=base, **options)
            return make_run(root)

        with tempfile.TemporaryDirectory() as root:
            code, output, out, _ = self.run_main(
                root, trainer, "--epochs", "5", "--device", "cpu")

            self.assertEqual(code, 0)
            self.assertTrue(output.is_file())

        self.assertEqual((calls["epochs"], calls["device"]), (5, "cpu"))
        self.assertEqual(calls["base"], "yolov8n.pt")
        self.assertIn("check_setup.py --full", out)

    def test_device_is_not_forced_when_not_given(self):
        seen = {}

        def trainer(base, **options):
            seen.update(options)
            return make_run(root)

        with tempfile.TemporaryDirectory() as root:
            self.run_main(root, trainer)

        self.assertNotIn("device", seen)

    def test_missing_ultralytics_gives_install_advice(self):
        def trainer(base, **options):
            raise ImportError("No module named ultralytics")

        with tempfile.TemporaryDirectory() as root:
            code, output, _, err = self.run_main(root, trainer)

            self.assertEqual(code, 1)
            self.assertFalse(output.exists())

        self.assertIn("pip install -r requirements.txt", err)

    def test_run_that_produced_no_weights_is_reported(self):
        def trainer(base, **options):
            return Path(root) / "empty"

        with tempfile.TemporaryDirectory() as root:
            code, output, _, err = self.run_main(root, trainer)

            self.assertEqual(code, 1)
            self.assertFalse(output.exists())

        self.assertIn("no weights", err)

    def test_bad_dataset_stops_before_training(self):
        def trainer(base, **options):
            raise AssertionError("must not train")

        err = io.StringIO()

        with contextlib.redirect_stderr(err):
            code = te.main(["--data", "/nonexistent/data.yaml"],
                           trainer=trainer)

        self.assertEqual(code, 1)
        self.assertIn("Cannot start", err.getvalue())


if __name__ == "__main__":
    unittest.main()


class EvaluationTests(unittest.TestCase):

    SCORES = {"precision": 0.9, "recall": 0.85, "mAP50": 0.91,
              "mAP50-95": 0.7}

    def run_with(self, evaluator, *extra):
        def trainer(base, **options):
            return make_run(root)

        with tempfile.TemporaryDirectory() as root:
            data = make_dataset(root)
            output = Path(root) / "models" / "emergency_vehicle.pt"
            out = io.StringIO()

            with contextlib.redirect_stdout(out):
                code = te.main(["--data", str(data), "--output",
                                str(output), *extra], trainer=trainer,
                               evaluator=evaluator)

            installed = output.is_file()

        return code, installed, out.getvalue()

    def test_scores_are_printed_in_plain_words(self):
        code, _, out = self.run_with(lambda weights, data, split='val': self.SCORES)

        self.assertEqual(code, 0)
        self.assertIn("mAP@0.5 0.91", out)
        self.assertIn("good", out)

    def test_verdicts(self):
        for map50, word in ((0.85, "good"), (0.6, "usable"), (0.2, "weak")):
            text = te.describe_quality({**self.SCORES, "mAP50": map50})

            self.assertIn(word, text)

    def test_a_failing_evaluation_does_not_lose_the_weights(self):
        def broken(weights, data, split='val'):
            raise RuntimeError("val exploded")

        code, installed, out = self.run_with(broken)

        self.assertEqual(code, 0)
        self.assertTrue(installed)
        self.assertIn("Could not score the weights", out)

    def test_evaluation_can_be_skipped(self):
        called = []

        code, _, out = self.run_with(
            lambda w, d, split='val': called.append(1) or self.SCORES, "--no-evaluate")

        self.assertEqual((code, called), (0, []))
        self.assertNotIn("mAP", out)


    def test_test_split_is_scored_when_the_dataset_has_one(self):
        splits = []

        with tempfile.TemporaryDirectory() as root:
            data = make_dataset(root)
            test_dir = data.parent / "images" / "test"
            test_dir.mkdir(parents=True)
            (test_dir / "a.jpg").write_bytes(b"x")
            report = Path(root) / "report.json"

            def evaluator(weights, data, split="val"):
                splits.append(split)
                return {**self.SCORES, "per_class": {"ambulance": {
                    "mAP50": 0.9, "mAP50-95": 0.7}}}

            with contextlib.redirect_stdout(io.StringIO()) as out:
                te.main(["--data", str(data), "--output",
                         str(Path(root) / "m.pt"), "--report", str(report)],
                        trainer=lambda base, **o: make_run(root),
                        evaluator=evaluator)

            saved = json.loads(report.read_text())

        self.assertEqual(splits, ["val", "test"])
        self.assertEqual(set(saved), {"val", "test"})
        self.assertIn("test images", out.getvalue())
        self.assertIn("ambulance: mAP@0.5 0.90", out.getvalue())

    def test_time_cap_is_passed_to_training(self):
        seen = {}

        def trainer(base, **options):
            seen.update(options)
            return make_run(root)

        with tempfile.TemporaryDirectory() as root:
            data = make_dataset(root)

            with contextlib.redirect_stdout(io.StringIO()):
                te.main(["--data", str(data), "--output",
                         str(Path(root) / "m.pt"), "--time", "4.5",
                         "--no-evaluate"], trainer=trainer)

        self.assertEqual(seen["time"], 4.5)


class NotebookTests(unittest.TestCase):

    def test_the_colab_notebook_is_valid_and_runs_the_real_script(self):
        import json

        path = Path(te.__file__).parent / "notebooks" / \
            "train_emergency_colab.ipynb"
        notebook = json.loads(path.read_text())
        source = "\n".join("".join(c["source"]) for c in notebook["cells"])

        self.assertEqual(notebook["nbformat"], 4)
        self.assertIn("python train_emergency.py", source)
        self.assertIn("files.download('models/emergency_vehicle.pt')", source)

        # Every option the notebook passes must exist in the script.
        parser = te.build_parser()
        parser.parse_args(["--epochs", "60", "--device", "0", "--batch", "-1"])


    def test_the_new_data_notebook_uses_real_scripts_and_options(self):
        import json
        import build_emergency_dataset as bd

        path = Path(te.__file__).parent / "notebooks" / \
            "train_emergency_colab_new_data.ipynb"
        notebook = json.loads(path.read_text())
        source = "\n".join("".join(c["source"]) for c in notebook["cells"])

        self.assertIn("python build_emergency_dataset.py", source)
        self.assertIn("python train_emergency.py --data", source)
        self.assertIn('supervision>=0.20,<0.31', source)

        te.build_parser().parse_args(
            ["--data", "x.yaml", "--epochs", "80", "--device", "0",
             "--batch", "-1", "--report", "emergency_scores.json"])
        bd.build_parser().parse_args(["--source", "a", "--source", "b:fire_truck"])

        # The forced class the notebook uses must be one the script knows.
        self.assertIn("fire_truck", bd.CLASSES)
