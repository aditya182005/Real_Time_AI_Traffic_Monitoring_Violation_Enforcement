"""Merge several downloaded YOLO datasets into one 3-class emergency dataset.

Classes: 0 ambulance, 1 fire_truck, 2 police_car.

    python build_emergency_dataset.py \
        --source downloads/a --source downloads/b --source downloads/c:fire_truck

Each ``--source`` is a folder in YOLO format with a ``data.yaml`` (what
Roboflow's "YOLOv8" export gives you). Class names are mapped by keyword
(ambulance / fire / police). Add ``:ambulance``, ``:fire_truck`` or
``:police_car`` to a source when every box in it is that one class and the
names are meaningless.

What it does, so the result can be trusted:

* Boxes of other classes (siren, car, ...) are dropped.
* An image is kept as a *negative* only when everything labelled in it is an
  ordinary vehicle. An image with an unrecognised class is dropped, because
  it might hold an unlabelled emergency vehicle.
* Exact duplicate images are removed, polygons become boxes, and bad boxes
  are discarded.
* Everything is re-split 80/10/10 *by original photo*, so augmented copies of
  one photo never sit in both train and test (that would inflate the scores).
"""

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLASSES = ["ambulance", "fire_truck", "police_car"]
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ORDINARY = {
    "car", "cars", "truck", "bus", "bicycle", "motorcycle", "motorbike",
    "bike", "van", "rickshaw", "autorickshaw", "auto", "cng", "vehicle",
    "pickup", "taxi", "person", "pedestrian", "tractor", "minibus",
}
SPLITS = ("train", "val", "test")


def class_for_name(name):
    """0, 1, 2 for an emergency class name, ``"ordinary"``, or None."""

    key = re.sub(r"[^a-z0-9]+", "", str(name).lower())

    if "ambulance" in key:
        return 0

    if "firetruck" in key or "fireengine" in key or "firefighter" in key \
            or key.startswith("fire") or "firebrigade" in key:
        return 1

    if "police" in key:
        return 2

    if key in ORDINARY:
        return "ordinary"

    return None


def read_names(data_yaml):
    """Class names from a data.yaml, without needing PyYAML."""

    text = Path(data_yaml).read_text(encoding="utf-8")
    inline = re.search(r"^names:\s*\[(.*?)\]", text, re.M | re.S)

    if inline:
        return [n.strip().strip("'\"") for n in inline.group(1).split(",")
                if n.strip()]

    block = re.search(r"^names:\s*\n((?:[ \t]+.*\n?)+)", text, re.M)

    if not block:
        raise ValueError(f"No class names found in {data_yaml}")

    pairs = {}
    listed = []

    for line in block.group(1).splitlines():
        line = line.strip()

        if line.startswith("- "):
            listed.append(line[2:].strip().strip("'\""))
        elif ":" in line:
            number, name = line.split(":", 1)
            pairs[int(number)] = name.strip().strip("'\"")

    if listed:
        return listed

    return [pairs[i] for i in sorted(pairs)]


def to_box(values):
    """``x y w h`` for a 4-number row; a polygon becomes its bounding box."""

    if len(values) == 4:
        return values

    if len(values) >= 6 and len(values) % 2 == 0:
        xs, ys = values[0::2], values[1::2]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

        return [(x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0]

    return None


def clean_box(box):
    x, y, w, h = box
    x0, x1 = max(0.0, x - w / 2), min(1.0, x + w / 2)
    y0, y1 = max(0.0, y - h / 2), min(1.0, y + h / 2)
    w, h = x1 - x0, y1 - y0

    if w < 0.01 or h < 0.01:
        return None

    return [(x0 + x1) / 2, (y0 + y1) / 2, w, h]


def photo_key(stem):
    """The original photo a Roboflow file came from (drops ``.rf.<hash>``)."""

    return re.split(r"[._-]?(?:jpe?g|png)?\.rf\.", stem, maxsplit=1)[0]


def parse_source(text):
    path, _, forced = text.partition(":")

    # A Windows path such as C:\x has a colon; only treat the tail as a class
    # when it is one.
    if forced and forced not in CLASSES:
        path, forced = text, ""

    return Path(path), (CLASSES.index(forced) if forced else None)


def load_source(folder, forced_class, tag, stats):
    """Yield ``(group, image_path, rows)`` for one downloaded dataset."""

    folder = Path(folder)
    names = read_names(folder / "data.yaml")
    mapping = {}

    for number, name in enumerate(names):
        mapping[number] = forced_class if forced_class is not None \
            else class_for_name(name)

    stats[tag]["classes"] = {
        name: ("ambulance fire_truck police_car".split()[mapping[i]]
               if isinstance(mapping[i], int) else mapping[i] or "UNKNOWN")
        for i, name in enumerate(names)}

    for split in SPLITS + ("valid",):
        images = folder / split / "images"

        if not images.is_dir():
            images = folder / "images" / split

        labels = images.parent / "labels" if images.parent.name == split \
            else folder / "labels" / split

        if not images.is_dir():
            continue

        for image in sorted(images.iterdir()):
            if image.suffix.lower() not in IMAGE_TYPES:
                continue

            label = labels / f"{image.stem}.txt"
            rows, kinds = [], set()

            if label.is_file():
                for line in label.read_text().splitlines():
                    parts = line.split()

                    if len(parts) < 5:
                        continue

                    try:
                        number = int(float(parts[0]))
                        box = to_box([float(v) for v in parts[1:]])
                    except ValueError:
                        stats[tag]["bad_rows"] += 1
                        continue

                    kind = mapping.get(number)

                    if isinstance(kind, int):
                        box = clean_box(box) if box else None

                        if box is None:
                            stats[tag]["bad_rows"] += 1
                            continue

                        rows.append((kind, box))
                    kinds.add("ordinary" if kind == "ordinary" else
                              kind if kind is not None else "unknown")
            else:
                kinds.add("unlabelled")

            if rows:
                pass
            elif kinds and kinds <= {"ordinary"}:
                pass  # a true negative: only ordinary vehicles are labelled
            else:
                stats[tag]["dropped_unsure"] += 1
                continue

            yield f"{tag}/{photo_key(image.stem)}", image, rows


def build(sources, output, seed=0, val=0.1, test=0.1, include=None):
    output = Path(output)
    sources = list(sources)
    stats = defaultdict(lambda: {"dropped_unsure": 0, "bad_rows": 0})
    items = []

    for number, text in enumerate(sources):
        folder, forced = parse_source(text)
        tag = f"s{number}"
        stats[tag]["folder"] = str(folder)

        items.extend(load_source(folder, forced, tag, stats))

    if include:
        existing = Path(include)
        tag = "existing"
        stats[tag]["folder"] = str(existing)

        for split in SPLITS:
            images = existing / "images" / split

            if not images.is_dir():
                continue

            for image in sorted(images.iterdir()):
                if image.suffix.lower() not in IMAGE_TYPES:
                    continue

                label = existing / "labels" / split / f"{image.stem}.txt"
                rows = []

                for line in label.read_text().splitlines():
                    parts = line.split()

                    if len(parts) == 5:
                        rows.append((int(parts[0]),
                                     [float(v) for v in parts[1:]]))

                items.append((f"{tag}/{photo_key(image.stem)}", image, rows))

    # Remove exact duplicates (the same file in two sources).
    seen, unique, duplicates = set(), [], 0

    for group, image, rows in items:
        digest = hashlib.md5(image.read_bytes()).hexdigest()

        if digest in seen:
            duplicates += 1
            continue

        seen.add(digest)
        unique.append((group, image, rows))

    groups = defaultdict(list)

    for item in unique:
        groups[item[0]].append(item)

    # Split by photo, aiming for the same share of each class in every split.
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    placement = {}
    target = {"val": val, "test": test, "train": 1 - val - test}
    counts = {s: Counter() for s in SPLITS}
    sizes = Counter()

    def main_class(key):
        found = Counter(c for _, _, rows in groups[key] for c, _ in rows)

        return min(found, key=lambda c: sum(counts[s][c] for s in SPLITS)) \
            if found else -1

    for key in keys:
        wanted = main_class(key)
        total = sum(sizes.values()) + 1

        def shortfall(split):
            have = counts[split][wanted] if wanted >= 0 else sizes[split]
            all_have = sum(counts[s][wanted] for s in SPLITS) \
                if wanted >= 0 else total
            return target[split] - have / max(1, all_have)

        split = max(SPLITS, key=shortfall)
        placement[key] = split
        sizes[split] += len(groups[key])

        for _, _, rows in groups[key]:
            counts[split].update(c for c, _ in rows)

    if output.exists():
        shutil.rmtree(output)

    for split in SPLITS:
        (output / "images" / split).mkdir(parents=True)
        (output / "labels" / split).mkdir(parents=True)

    negatives = Counter()

    for key, members in groups.items():
        split = placement[key]

        for group, image, rows in members:
            name = group.replace("/", "_") + "__" + image.stem
            name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:150]
            shutil.copy2(image, output / "images" / split /
                         (name + image.suffix.lower()))
            (output / "labels" / split / (name + ".txt")).write_text(
                "".join(f"{c} {b[0]:.6f} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f}\n"
                        for c, b in rows))

            if not rows:
                negatives[split] += 1

    (output / "data.yaml").write_text(
        "# No 'path:' key on purpose: Ultralytics resolves these relative to\n"
        "# this file, so it works on any machine.\n"
        "train: images/train\nval: images/val\ntest: images/test\n\nnames:\n"
        + "".join(f"  {i}: {n}\n" for i, n in enumerate(CLASSES)))

    report = {
        "sources": {k: v for k, v in stats.items()},
        "duplicates_removed": duplicates,
        "splits": {
            s: {"images": sizes[s], "negatives": negatives[s],
                "boxes": {CLASSES[c]: counts[s][c] for c in range(3)}}
            for s in SPLITS},
    }
    (output / "dataset_report.json").write_text(json.dumps(report, indent=2))

    return report


def print_report(report):
    for tag, info in report["sources"].items():
        print(f"\n[{tag}] {info.get('folder')}")

        for name, mapped in info.get("classes", {}).items():
            print(f"    {name!r:28} -> {mapped}")

        print(f"    dropped (unsure): {info['dropped_unsure']}, "
              f"bad rows: {info['bad_rows']}")

    print(f"\nDuplicate images removed: {report['duplicates_removed']}\n")
    print(f"{'split':6} {'images':>7} {'neg':>5} " +
          " ".join(f"{c:>11}" for c in CLASSES))

    for split, info in report["splits"].items():
        print(f"{split:6} {info['images']:7} {info['negatives']:5} " +
              " ".join(f"{info['boxes'][c]:11}" for c in CLASSES))

    for split, info in report["splits"].items():
        for c in CLASSES:
            if info["boxes"][c] < 10:
                print(f"WARNING: only {info['boxes'][c]} {c} boxes in "
                      f"{split}; its scores will be unreliable.")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", action="append", required=True,
                        help="a downloaded YOLO dataset folder (repeatable)")
    parser.add_argument("--output", default=str(ROOT / "data" /
                                                "emergency_vehicle_new"))
    parser.add_argument("--include-existing", default=None, metavar="DIR",
                        help="also add the dataset already in the repo, "
                             "for example data/emergency_vehicle")
    parser.add_argument("--seed", type=int, default=0)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        report = build(args.source, args.output, seed=args.seed,
                       include=args.include_existing)
    except (OSError, ValueError) as exc:
        print(f"Cannot build the dataset: {exc}", file=sys.stderr)
        return 1

    print_report(report)
    print(f"\nWritten to {args.output}. Train with:\n"
          f"  python train_emergency.py --data {args.output}/data.yaml")

    return 0


if __name__ == "__main__":
    sys.exit(main())
