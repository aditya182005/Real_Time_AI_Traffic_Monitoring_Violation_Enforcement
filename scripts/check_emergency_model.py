"""Check the emergency model on pictures it was NOT trained on.

    python scripts/check_emergency_model.py
    python scripts/check_emergency_model.py --data other_dataset/data.yaml --conf 0.4

It reports three things, in plain words:

1. Scores (mAP, precision, recall) on the chosen split.
2. FALSE ALARMS: how many pictures with no emergency vehicle (empty label
   files) the model still flags. Ordinary cars, vans and buses are the
   everyday risk for a traffic camera.
3. MISSED LABELS: pictures kept in <dataset>/_review/missing_labels, which
   all contain an emergency vehicle. The share the model finds shows how it
   copes with a different source of pictures.

With ``--negatives DIR`` it also tests a folder of REAL pictures with no
emergency vehicle that were never used for training (cars, trucks, buses on
real roads), and says which wrong class each false alarm picked, for example
"truck -> fire_truck". This is the honest check for the "every truck is a fire
truck" problem; keep that folder out of training.
"""

TARGET_FALSE_ALARM_SHARE = 0.05

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_YAML = ROOT / "data" / "emergency_vehicle" / "data.yaml"
WEIGHTS = ROOT / "models" / "emergency_vehicle.pt"
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def images_in(folder):
    folder = Path(folder)

    if not folder.is_dir():
        return []

    return sorted(p for p in folder.iterdir()
                  if p.suffix.lower() in IMAGE_TYPES)


def negative_images(data_yaml, split):
    """Pictures of the split whose label file has no boxes."""

    base = Path(data_yaml).parent
    found = []

    for image in images_in(base / "images" / split):
        label = base / "labels" / split / f"{image.stem}.txt"

        if label.is_file() and not label.read_text().strip():
            found.append(image)

    return found


def review_images(data_yaml):
    base = Path(data_yaml).parent / "_review" / "missing_labels"

    return [p for split in ("train", "val", "test")
            for p in images_in(base / split / "images")]


def share_flagged(images, detector):
    """``(flagged, total)``: pictures with at least one detection."""

    counts = detector(images)

    return sum(1 for c in counts if c > 0), len(counts)


def _ultralytics_detector(weights, conf):
    from ultralytics import YOLO

    model = YOLO(str(weights))

    def run(images):
        counts = []

        for result in model.predict(source=[str(p) for p in images],
                                    conf=conf, verbose=False, stream=True):
            counts.append(len(result.boxes))

        return counts

    return run


def _ultralytics_classifier(weights, conf):
    """Per picture, the ``(class_name, confidence)`` of every detection."""

    from ultralytics import YOLO

    model = YOLO(str(weights))

    def run(images):
        found = []

        for result in model.predict(source=[str(p) for p in images],
                                    conf=conf, verbose=False, stream=True):
            found.append([(model.names[int(b.cls[0])], float(b.conf[0]))
                          for b in result.boxes])

        return found

    return run


def false_alarm_summary(images, found):
    """``(flagged_pictures, by_class, worst)`` from per-picture detections."""

    flagged = [(img, det) for img, det in zip(images, found) if det]
    by_class = Counter(max(det, key=lambda d: d[1])[0]
                       for _, det in flagged)
    worst = sorted(flagged, key=lambda f: -max(d[1] for d in f[1]))

    return len(flagged), by_class, worst


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--weights", default=str(WEIGHTS))
    parser.add_argument("--data", default=str(DATA_YAML))
    parser.add_argument("--split", default="test")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="confidence needed to count as a detection")
    parser.add_argument("--negatives", default=None, metavar="DIR",
                        help="a folder of real pictures with no emergency "
                             "vehicle that were NOT used for training")

    return parser


def main(argv=None, detector_factory=_ultralytics_detector,
         evaluator=None, classifier_factory=_ultralytics_classifier):
    args = build_parser().parse_args(argv)

    if not Path(args.weights).is_file():
        print(f"Model not found: {args.weights}", file=sys.stderr)
        return 1

    if not Path(args.data).is_file():
        print(f"Dataset not found: {args.data}", file=sys.stderr)
        return 1

    if evaluator is None:
        from train_emergency import _ultralytics_evaluator as evaluator

    detector = detector_factory(args.weights, args.conf)

    print(f"Model {args.weights}\nPictures {args.data} ({args.split})\n")

    try:
        scores = evaluator(args.weights, args.data, split=args.split)
        print(f"1. Scores: mAP@0.5 {scores['mAP50']:.2f}, precision "
              f"{scores['precision']:.2f}, recall {scores['recall']:.2f}")

        for name, values in scores.get("per_class", {}).items():
            print(f"     class {name}: mAP@0.5 {values['mAP50']:.2f}")
    except Exception as exc:
        print(f"1. Scores unavailable ({type(exc).__name__}: {exc})")

    negatives = negative_images(args.data, args.split)

    if negatives:
        flagged, total = share_flagged(negatives, detector)
        print(f"\n2. False alarms: {flagged} of {total} pictures with no "
              f"emergency vehicle were flagged ({100 * flagged / total:.0f}%) "
              f"at confidence {args.conf}.")
    else:
        print(f"\n2. False alarms: no empty-label pictures in "
              f"'{args.split}', so this cannot be measured here.")

    review = review_images(args.data)

    if review:
        flagged, total = share_flagged(review, detector)
        print(f"\n3. Missed labels: the model found an emergency vehicle in "
              f"{flagged} of {total} pictures that all contain one "
              f"({100 * flagged / total:.0f}%).")
    else:
        print("\n3. Missed labels: no _review/missing_labels folder found.")

    if args.negatives:
        images = [p for p in sorted(Path(args.negatives).rglob("*"))
                  if p.suffix.lower() in IMAGE_TYPES]

        if not images:
            print(f"\n4. Real negatives: no pictures in {args.negatives}.")
        else:
            found = classifier_factory(args.weights, args.conf)(images)
            count, by_class, worst = false_alarm_summary(images, found)
            share = count / len(images)
            print(f"\n4. Real negatives: {count} of {len(images)} pictures "
                  f"with no emergency vehicle were flagged "
                  f"({100 * share:.1f}%) at confidence {args.conf}.")

            for name, number in by_class.most_common():
                print(f"     wrongly called {name}: {number}")

            for image, det in worst[:10]:
                top = max(det, key=lambda d: d[1])
                print(f"     {image.name}: {top[0]} {top[1]:.2f}")

            verdict = "GOOD ENOUGH" if share <= TARGET_FALSE_ALARM_SHARE \
                else "TOO MANY FALSE ALARMS"
            print(f"   Target: at most {100 * TARGET_FALSE_ALARM_SHARE:.0f}%"
                  f" -> {verdict}. Raise --conf or add more real negatives "
                  "and retrain if it is too high.")

    print("\nPictures from your own cameras are the final test.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
