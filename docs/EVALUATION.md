# Evaluation

## What is measured

| Area | Method | Status |
|---|---|---|
| Emergency detection | Ultralytics validation on the held-out test split: precision, recall, mAP@0.5, mAP@0.5:0.95, per class | Measured |
| Emergency false alarms | `scripts/check_emergency_model.py` on negatives | Measured on dataset negatives only |
| Violation detection | `scripts/evaluate.py` compares detected events with a hand-made truth CSV | Run on the demo video |
| Vehicle detection | Pretrained COCO YOLOv8n | Not evaluated here |
| Tracking | Needs labelled tracks | Not measured |
| FPS | Printed by `scripts/run_video.py` and `scripts/evaluate.py` | Hardware dependent |
| Twilio latency | Alerts page | Needs your account |

## Emergency model results

Test split, mAP@0.5: **0.95** overall (ambulance 0.94, fire truck 0.98, police
car 0.92), precision 0.94, recall 0.91.

## Caveats

* Test pictures are mostly close-up photos from public datasets; real CCTV
  frames look different. Expect lower accuracy on your cameras.
* Photos of the same scene may still appear across splits despite grouping.
* The false-alarm rate on real traffic footage has **not** been measured.
* The demo video is synthetic (photo patches on a road). It checks the rule
  logic, not real-world accuracy.

## Evaluate violations on your own clip

```bash
python scripts/evaluate.py --video clip.mp4 --truth truth.csv --speed --collisions
```

The demo truth file `data/videos/demo_all_checks_truth.csv` (see `data/samples/README.md`) shows the format. Report precision and
recall per violation type, and review false alarms by hand.
