# Emergency-vehicle dataset

YOLO format, classes: `0 ambulance`, `1 fire_truck`, `2 police_car`.

## What was cleaned

Every image with an empty label file (409) was checked by eye.

* **85 were emergency vehicles whose boxes were simply missing** (an
  empty label file tells YOLO "there is nothing here", which teaches the
  model to ignore real ambulances and also makes validation scores look
  worse than they are). They are moved, unchanged, to
  `_review/missing_labels/<split>/` so nothing is lost and git can undo it.
  Ultralytics only reads `images/` and `labels/`, so training ignores them.
* **324 stay as true negatives** (ordinary cars, vans, buses, trucks) and
  help the model avoid false alarms.
* One label row in `train` was a polygon (123 values); it is now a box.

| split | images | ambulance | fire_truck | police_car | negatives |
|-------|--------|-----------|------------|------------|-----------|
| train | 1317   | 236       | 436        | 687        | 227       |
| val   | 368    | 64        | 129        | 190        | 63        |
| test  | 178    | 30        | 49         | 92         | 34        |

## Known limits

* Most pictures are close-up, daylight photos of single vehicles, not
  CCTV frames, so expect more misses on real traffic footage than the test
  scores suggest. Add frames from your own cameras to fix this.
* Boxes inside the images were spot-checked, not all verified.
* The 85 quarantined images can be labelled and moved back to improve
  the next round (a trained model can suggest the boxes).
