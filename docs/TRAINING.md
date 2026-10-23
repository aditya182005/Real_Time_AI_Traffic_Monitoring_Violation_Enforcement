# Training the emergency-vehicle model

The emergency model is a YOLOv8 detector with three classes: `0 ambulance`,
`1 fire_truck`, `2 police_car`. Weights go to `models/emergency_vehicle.pt`.
Without them the rest of the app works; only emergency priority is off.

The project no longer ships a training dataset. You build one from public
data with the Colab notebook (recommended) or the scripts.

## Why "every truck is a fire truck"

A model trained on photos that are all emergency vehicles has no idea what an
*ordinary* truck or car looks like in a real street, so it guesses the closest
emergency class: trucks become fire trucks, cars become police cars. The cure
is **real negatives**: many pictures of ordinary cars, trucks and buses that
must not be flagged, in the kind of scene the camera sees. Roughly a third to
a half of the training pictures should be negatives.

## Option A: Google Colab (recommended)

1. Merge the latest `main`, then open `notebooks/train_emergency_colab.ipynb`
   in Colab (File > Open notebook > GitHub).
2. Runtime > Change runtime type > T4 GPU. Get a free Roboflow API key.
3. Run the cells in order. The notebook:
   1. downloads the public emergency-vehicle datasets and merges them,
   2. downloads real street pictures of cars, trucks and buses (COCO) as
      negatives and sets 400 aside, never used for training,
   3. optionally adds frames from your own videos as negatives,
   4. trains, then shows negatives the model flags so you can remove any that
      really contain an emergency vehicle, and retrains if you did,
   5. tests on the held-out pictures and prints the share wrongly flagged and
      as which class.
4. Download `emergency_vehicle.pt` and `results.zip`, and put the `.pt` in `models/`.

**Good enough:** 5% or fewer of the held-out ordinary pictures flagged, and a
test mAP@0.5 above about 0.8. If not, the notebook says what to try.

## Option B: your own computer (needs a GPU to be practical)

```bash
pip install ultralytics roboflow
python scripts/fetch_coco_negatives.py --output data/negatives_all --max-images 2400
# set 400 pictures aside in data/negatives_heldout; move the rest to data/negatives_train
python scripts/build_emergency_dataset.py \
  --source downloads/dataset_a --source downloads/dataset_b \
  --negatives data/negatives_train --max-negatives 1500
python scripts/train_emergency.py --epochs 60 --batch -1 --device 0
python scripts/check_emergency_model.py --negatives data/negatives_heldout --conf 0.5
```

`scripts/train_emergency.py` options: `--epochs --imgsz --batch --device --base
--data --name --output --time --patience --report --no-evaluate`. `--time`
caps training hours; `--patience` stops early when validation stalls.

## Your own footage is the best negative data

Frames from your cameras with nothing special happening teach the model what
your road looks like:

```bash
python scripts/extract_frames.py --video data/my_media/road.mp4 --output data/negatives_own --every-seconds 2
```

Only use clips with no emergency vehicle in them, glance through the pictures,
then add `--negatives data/negatives_own` to the build command.

## What the build step does (`scripts/build_emergency_dataset.py`)

* Maps each source's class names to the three classes; other classes are
  dropped, and an image with an unrecognised class is dropped too (it might
  hold an unlabelled emergency vehicle).
* Converts polygons to boxes, removes exact duplicates, discards bad boxes.
* Splits 80/10/10 *by original photo* (Roboflow augmentations share a hash), so
  near copies never land in both train and test.
* Adds `--negatives` folders as empty-label pictures, optionally capped by
  `--max-negatives`, and warns if negatives are under 5% of a split.

## Data and licences

Roboflow Universe datasets are CC BY 4.0: keep their credits when you publish.
COCO annotations are CC BY 4.0; COCO photos come from Flickr under various
licences, so use them for training negatives only and do not redistribute them.
The datasets are git-ignored.

## Check a model

```bash
python scripts/check_emergency_model.py --weights models/emergency_vehicle.pt --negatives data/negatives_heldout
```

It prints the scores on the test split, the share of empty pictures flagged,
and for `--negatives` the share of real ordinary pictures flagged with the wrong
class each one picked. See [EVALUATION.md](EVALUATION.md).

## Quick fix without retraining

If your current model flags ordinary trucks and cars, raise the confidence it
needs: set `EMERGENCY_CONFIDENCE=0.85` in `.env` (default 0.65). You will miss
some real emergency vehicles. Retraining with real negatives is the proper fix.
