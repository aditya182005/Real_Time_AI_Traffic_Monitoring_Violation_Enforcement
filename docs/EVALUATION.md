# Evaluation

## What is measured

| Area | Method | Status |
|---|---|---|
| Emergency detection | Ultralytics validation on the held-out test split: precision, recall, mAP@0.5, mAP@0.5:0.95, per class | Measured (below) |
| Emergency false alarms | `scripts/check_emergency_model.py --negatives DIR` on real ordinary pictures kept out of training | Measure after retraining (target 5% or less) |
| Violation detection | `scripts/evaluate.py` compares detected events with a hand-made truth CSV | Run on the demo video |
| Vehicle detection | Pretrained COCO YOLOv8n | Not evaluated here |
| Tracking | Needs labelled tracks | Not measured |
| FPS | Printed by `scripts/run_video.py` and `scripts/evaluate.py` | Hardware dependent |
| Twilio latency | Alerts page | Needs your account |

## Emergency model results

Model trained with `notebooks/train_emergency_colab.ipynb` (60 epochs, YOLOv8n,
3,104 training pictures of which 1,239 are real ordinary-vehicle negatives).

**Test split** (391 pictures, 156 of them ordinary vehicles): mAP@0.5 **0.91**
(ambulance 0.85, fire truck 0.96, police car 0.93), precision 0.96, recall 0.85,
mAP@0.5:0.95 0.79. Very few class mix-ups (5 ambulances called fire trucks).

**Held-out real negatives** (400 COCO photos of cars, trucks and buses, about
half trucks/buses, never used for training), flagged as an emergency vehicle:

| Confidence | Flagged | Wrong class picked |
|---|---|---|
| 0.25 | 16 (4.0%) | police car 6, fire truck 6, ambulance 4 |
| 0.4 | 12 (3.0%) | police car 4, fire truck 6, ambulance 2 |
| 0.5 | 7 (1.8%) | fire truck 5, ambulance 1, police car 1 |
| **0.65 (app default)** | **4 (1.0%)** | fire truck 3, police car 1 |
| 0.85 | 4 (1.0%) | fire truck 3, police car 1 |

**Real emergency test pictures found** (231): 98.7% at 0.25, 98.3% at 0.5,
**97.4% at 0.65**, 90.0% at 0.85. Raising the confidence above 0.65 removes no
more false alarms here and loses real detections, so the default is kept.

## Caveats

* Test pictures are mostly close-up photos from public datasets; real CCTV
  frames look different. Expect lower accuracy on your cameras.
* Photos of the same scene may still appear across splits despite grouping.
* The held-out negatives are public COCO photos. The false-alarm rate on your own cameras has **not** been measured: run `scripts/footage_report.py`.
* The few pictures still flagged at 0.85 may be real emergency vehicles that escaped the caption filter in COCO; check them by eye.
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
