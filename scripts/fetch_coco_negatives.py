"""Download real street pictures of ordinary cars, trucks and buses.

    python scripts/fetch_coco_negatives.py --output data/negatives_coco

These are *negatives* for the emergency model: pictures that must NOT be
flagged. A model trained only on emergency vehicles tends to call every truck
a fire truck and every car a police car, because it has never been shown
ordinary ones in real scenes. This takes them from the COCO 2017 validation
set (about 5,000 photos; the annotations are CC BY 4.0, the photos come from
Flickr under various licences, so use them for training, not redistribution).

How it picks pictures:

* a car, truck or bus must take up a visible part of the picture;
* pictures whose caption mentions an ambulance, fire engine, police, siren or
  similar are dropped, because COCO labels those as plain "car" or "truck";
* about half the pictures contain a truck or a bus, the usual look-alikes of
  fire trucks and ambulances.

Needs internet (about 250 MB for the annotations, then one small file per
picture). Run it in Colab or on a normal computer, not behind a firewall.
Even so, glance through the folder: a few emergency vehicles can still slip
through, and the notebook has a step that shows suspicious ones.
"""

import argparse
import json
import random
import re
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANNOTATIONS_URL = ("http://images.cocodataset.org/annotations/"
                   "annotations_trainval2017.zip")
IMAGE_URL = "http://images.cocodataset.org/val2017/{name}"
CAR, BUS, TRUCK = 3, 6, 8
VEHICLES = {CAR, BUS, TRUCK}
EXCLUDE_WORDS = re.compile(
    r"ambulance|fire\s*(truck|engine|fighter|man|department|hydrant)|"
    r"firetruck|police|cop\b|siren|emergency|paramedic|rescue|"
    r"sheriff|patrol", re.IGNORECASE)


def vehicle_stats(instances):
    """{image_id: {'area': pixels of vehicles, 'big': pixels, 'heavy': bool}}"""

    images = {i["id"]: i for i in instances["images"]}
    stats = {}

    for ann in instances["annotations"]:
        if ann["category_id"] not in VEHICLES or ann.get("iscrowd"):
            continue

        image = images.get(ann["image_id"])

        if image is None:
            continue

        entry = stats.setdefault(
            ann["image_id"],
            {"file": image["file_name"],
             "total": image["width"] * image["height"],
             "area": 0.0, "heavy": False})
        entry["area"] += ann["area"]
        entry["heavy"] = entry["heavy"] or ann["category_id"] in (BUS, TRUCK)

    return stats


def flagged_by_caption(captions):
    """Image ids whose captions suggest an emergency vehicle."""

    return {c["image_id"] for c in captions["annotations"]
            if EXCLUDE_WORDS.search(c["caption"])}


def select(instances, captions, count, min_area=0.03, heavy_share=0.5,
           seed=0):
    """Choose file names: visible vehicles, no emergency captions."""

    bad = flagged_by_caption(captions)
    usable = [(i, s) for i, s in vehicle_stats(instances).items()
              if i not in bad and s["area"] / s["total"] >= min_area]
    heavy = sorted(s["file"] for _, s in usable if s["heavy"])
    light = sorted(s["file"] for _, s in usable if not s["heavy"])
    rng = random.Random(seed)
    rng.shuffle(heavy)
    rng.shuffle(light)
    want_heavy = min(len(heavy), round(count * heavy_share))
    chosen = heavy[:want_heavy] + light[:count - want_heavy]

    if len(chosen) < count:           # not enough light ones: top up
        chosen += heavy[want_heavy:want_heavy + count - len(chosen)]

    return sorted(chosen)


def _download(url, target):
    target = Path(target)

    if target.exists() and target.stat().st_size:
        return True

    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()

        target.write_bytes(data)

        return True
    except OSError:
        return False


def load_annotations(cache):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    names = ("instances_val2017.json", "captions_val2017.json")

    if not all((cache / n).is_file() for n in names):
        archive = cache / "annotations_trainval2017.zip"
        print("Downloading COCO annotations (about 250 MB) ...", flush=True)

        if not _download(ANNOTATIONS_URL, archive):
            raise OSError("could not download the COCO annotations")

        with zipfile.ZipFile(archive) as zf:
            for name in names:
                (cache / name).write_bytes(zf.read(f"annotations/{name}"))

    return [json.loads((cache / n).read_text()) for n in names]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output", default=str(ROOT / "data" /
                                                "negatives_coco"))
    parser.add_argument("--cache", default=str(ROOT / "data" / ".coco_cache"))
    parser.add_argument("--max-images", type=int, default=1500)
    parser.add_argument("--heavy-share", type=float, default=0.5,
                        help="share of pictures with a truck or bus")
    parser.add_argument("--min-area", type=float, default=0.03,
                        help="vehicles must cover this share of the picture")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    try:
        instances, captions = load_annotations(args.cache)
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        print(f"Cannot get the COCO annotations: {exc}", file=sys.stderr)
        return 1

    names = select(instances, captions, args.max_images, args.min_area,
                   args.heavy_share, args.seed)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {len(names)} pictures to {out} ...", flush=True)

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(
            lambda n: (n, _download(IMAGE_URL.format(name=n), out / n)),
            names))

    failed = [n for n, ok in results if not ok]
    (out / "SOURCE.txt").write_text(
        "COCO 2017 validation pictures (annotations CC BY 4.0; photos from "
        "Flickr under various licences). Selected as cars, trucks and buses "
        "without emergency captions. For training negatives only.\n")
    print(f"Done: {len(names) - len(failed)} pictures"
          + (f", {len(failed)} failed" if failed else "") + ".")

    return 0 if len(failed) < len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
