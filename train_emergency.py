"""Train the emergency-vehicle model and install it where the app looks.

    python train_emergency.py                 # 30 epochs
    python train_emergency.py --epochs 60 --device 0

On a CPU this takes hours. A GPU, for example a free Google Colab session,
is far faster: upload the project, run this there, then download
models/emergency_vehicle.pt.

When training finishes the best weights are copied to
models/emergency_vehicle.pt, which is what the app and check_setup.py use.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_YAML = ROOT / "data" / "emergency_vehicle" / "data.yaml"
INSTALLED_WEIGHTS = ROOT / "models" / "emergency_vehicle.pt"
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def check_dataset(data_yaml=DATA_YAML):
    """Fail early, with a clear message, if the dataset is incomplete.

    Returns ``{"train": n, "val": n}`` image counts.
    """

    data_yaml = Path(data_yaml)

    if not data_yaml.is_file():
        raise FileNotFoundError(f"Dataset file not found: {data_yaml}")

    counts = {}

    for split in ("train", "val"):
        images = data_yaml.parent / "images" / split
        labels = data_yaml.parent / "labels" / split

        if not images.is_dir() or not labels.is_dir():
            raise FileNotFoundError(
                f"Dataset folder missing: {images} and {labels} must both "
                "exist (YOLO format)."
            )

        count = sum(1 for f in images.iterdir()
                    if f.suffix.lower() in IMAGE_TYPES)

        if count == 0:
            raise ValueError(f"No images found in {images}.")

        counts[split] = count

    return counts


def find_best_weights(save_dir):
    """The weights file a finished training run left behind."""

    weights = Path(save_dir) / "weights"

    for name in ("best.pt", "last.pt"):
        if (weights / name).is_file():
            return weights / name

    raise FileNotFoundError(f"No trained weights found in {weights}.")


def install_weights(weights, target=INSTALLED_WEIGHTS):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(weights, target)

    return target


def _ultralytics_trainer(base, **options):
    """Train with Ultralytics and return the run folder."""

    from ultralytics import YOLO

    model = YOLO(base)
    model.train(**options)

    return Path(model.trainer.save_dir)


def _ultralytics_evaluator(weights, data, split="val"):
    """Score finished weights on a dataset split.

    Returns ``{"precision", "recall", "mAP50", "mAP50-95"}`` (0 to 1).
    """

    from ultralytics import YOLO

    metrics = YOLO(str(weights)).val(data=str(data), split=split,
                                     verbose=False).box

    return {
        "precision": float(metrics.mp),
        "recall": float(metrics.mr),
        "mAP50": float(metrics.map50),
        "mAP50-95": float(metrics.map),
    }


def describe_quality(scores):
    """A plain-language reading of the validation scores."""

    map50 = scores["mAP50"]

    if map50 >= 0.8:
        verdict = "good"
    elif map50 >= 0.5:
        verdict = "usable, but expect misses and false alarms"
    else:
        verdict = ("weak: train longer, or check the labels, before "
                   "relying on it")

    return (f"mAP@0.5 {map50:.2f}, precision {scores['precision']:.2f}, "
            f"recall {scores['recall']:.2f} on the validation images: "
            f"{verdict}.")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Train the emergency-vehicle model and install it."
    )
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8,
                        help="images per step; -1 picks automatically (GPU)")
    parser.add_argument("--device", default=None,
                        help="for example 0 for the first GPU, or cpu")
    parser.add_argument("--base", default="yolov8n.pt",
                        help="starting weights (downloaded if needed)")
    parser.add_argument("--data", default=str(DATA_YAML))
    parser.add_argument("--name", default="emergency_vehicle")
    parser.add_argument("--output", default=str(INSTALLED_WEIGHTS),
                        help="where the finished weights are installed")
    parser.add_argument("--no-evaluate", action="store_true",
                        help="skip scoring the weights on the validation "
                             "images after training")

    return parser


def main(argv=None, trainer=_ultralytics_trainer,
         evaluator=_ultralytics_evaluator):
    """``trainer`` (returns the run folder) and ``evaluator`` can be
    replaced in tests."""

    args = build_parser().parse_args(argv)

    try:
        counts = check_dataset(args.data)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 1

    print(f"Dataset: {counts['train']} training and {counts['val']} "
          "validation images.")

    options = dict(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        project=str(ROOT / "runs" / "detect"),
        name=args.name,
        exist_ok=True,
    )

    if args.device is not None:
        options["device"] = args.device

    try:
        save_dir = trainer(args.base, **options)
        weights = find_best_weights(save_dir)
    except ImportError:
        print("Ultralytics is not installed. Run: "
              "pip install -r requirements.txt", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Training finished but no weights were found: {exc}",
              file=sys.stderr)
        return 1

    installed = install_weights(weights, args.output)

    print(f"\nTraining completed. Weights installed at {installed}")

    if not args.no_evaluate:
        try:
            print(describe_quality(evaluator(installed, args.data)))
        except Exception as exc:  # scoring is a bonus; the weights are safe
            print(f"Could not score the weights ({type(exc).__name__}: "
                  f"{exc}). They are installed anyway.")

    print("Check it with: python check_setup.py --full")

    return 0


if __name__ == "__main__":
    sys.exit(main())
