# Training the emergency-vehicle model

The emergency model is a YOLOv8 detector with three classes: `0 ambulance`,
`1 fire_truck`, `2 police_car`. Weights go to `models/emergency_vehicle.pt`.
Without them the rest of the app works; only emergency priority is off.

## Datasets

Data comes from Roboflow Universe projects licensed CC BY 4.0. Credits are in
`data/emergency_vehicle/README.dataset.txt`. The bundled, cleaned dataset is in
`data/emergency_vehicle/` (train 1317 / val 368 / test 178 images).

### Cleaning rules (`scripts/build_emergency_dataset.py`, `scripts/train_emergency.py`)

* Polygon labels are converted to boxes.
* Images are split by original photo (Roboflow augmentations share a hash), so
  near copies never land in both train and test.
* Exact duplicates are removed.
* Empty-label images are either genuine negatives (kept) or missed positives
  (quarantined in `data/emergency_vehicle/_review/missing_labels/`, 85 images).
* Negatives matter: a first model trained with only 4 negatives raised false
  alarms on 97% of non-emergency pictures. The builder now warns below 5%.

## Option A: Google Colab (recommended)

1. Open `notebooks/train_emergency_colab.ipynb` (bundled data) or
   `notebooks/train_emergency_colab_new_data.ipynb` (downloads fresh Roboflow
   datasets; needs a free Roboflow API key).
2. Runtime > Change runtime type > T4 GPU.
3. Run all cells. Download `emergency_vehicle.pt` and `results.zip`.
4. Put the `.pt` in `models/`.

## Option B: your computer

```bash
pip install ultralytics
python scripts/train_emergency.py --epochs 50 --device cpu --time 1.5
```

Useful flags: `--epochs --imgsz --batch --device --base --data --name --output --time --patience --report --no-evaluate`.
`--time` caps training hours; `--patience` stops early when validation stalls.

## Option C: GitHub Actions

`.github/workflows/train-emergency.yml` trains on CPU and uploads the weights as an artifact.

## Build a new dataset

```bash
python scripts/build_emergency_dataset.py \
  --source owner/project:version --include-existing \
  --output data/emergency_vehicle_new
```

`--source` can repeat. `--include-existing` mixes in the current dataset so the
new one keeps its negatives. Read the printed report before training.

## Check the result

```bash
python scripts/check_emergency_model.py --weights models/emergency_vehicle.pt --split test
```

It prints scores, the share of false alarms on negatives and the share of
detections that hit images with missing labels. See [EVALUATION.md](EVALUATION.md).
