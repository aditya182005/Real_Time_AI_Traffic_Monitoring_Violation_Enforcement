# Evaluation

## What is measured

| Area | Method | Status |
|---|---|---|
| Emergency detection | Ultralytics validation on the held-out test split: precision, recall, mAP@0.5, mAP@0.5:0.95, per class | Measured |
| Emergency false alarms | `scripts/check_emergency_model.py --negatives DIR` on real ordinary pictures kept out of training | Measure after retraining (target 5% or less) |
| Violation detection | `scripts/evaluate.py` compares detected events with a hand-made truth CSV | Run on the demo video |
| Vehicle detection | Pretrained COCO YOLOv8n | Not evaluated here |
| Tracking | Needs labelled tracks | Not measured |
| FPS | Printed by `scripts/run_video.py` and `scripts/evaluate.py` | Hardware dependent |
| Twilio latency | Alerts page | Needs your account |

## Emergency model results

**These numbers are from the earlier model, trained on a dataset that has since been removed. It wrongly flagged ordinary trucks and cars on real footage. Retrain with the new notebook and replace them with the new held-out numbers.**

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

## Testing on real footage (step by step)

This is how to replace the "not measured" rows with real numbers.

1. **Collect clips** (10-60 seconds each, 5-10 clips is enough to start):
   * `clips/normal/`: ordinary traffic with **no** ambulance, fire truck or
     police car. Include a variety: day, night or evening, rain, busy, empty.
   * `clips/emergency/`: clips that clearly show an emergency vehicle.
   Use footage you have the right to use. The `clips/` folder is git-ignored.
2. **Make sure the model is in place**: `models/emergency_vehicle.pt`.
3. **Run the batch** (add the checks you want after `--`):

   ```bash
   python scripts/footage_report.py --normal clips/normal --emergency clips/emergency -- --speed --wrong-way --collisions
   ```

   On a CPU-only machine this takes a while; start with short clips.
4. **Read `outputs/footage_report.md`**: false alarms per hour of normal video,
   and how many emergency clips were detected at all.
5. **Check by eye**: open the annotated videos in `outputs/footage/` and look at
   each emergency event in a normal clip. If it really is not an emergency
   vehicle, it is a false alarm (the report counts every event as one, so a
   genuine one inside a "normal" clip means the clip was mislabelled).
6. **Record the numbers** in the README's Evaluation table, with the number and
   length of clips, so the claim can be checked.

To score violations (red light, speed, wrong way), write a truth CSV for one
clip by hand (see `data/videos/demo_all_checks_truth.csv`) and run
`python scripts/evaluate.py` on it.
