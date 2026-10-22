# Checking the outputs with photos and videos

A step-by-step way to see what the app produces, what it should produce, and
how to tell a good result from a bad one. Do the tests in order: A and B use
files that ship with the project and have known answers; C and D use your own.

## 0. Get ready

```bash
python scripts/check_setup.py        # packages, files, model
streamlit run app/main.py            # open http://localhost:8501
```

Open **Analyze footage**. You can use a file three ways: upload it, pick it from
the project (drop files in `data/my_media/` and they appear in the "Or pick ...
already in the project" lists), or use the bundled samples.

If `models/emergency_vehicle.pt` is missing, emergency detection is off (the
checkbox is greyed out). Everything else still works.

## A. Sample photos (known answers)

1. Analyze footage > **Images**.
2. In "Or pick pictures already in the project" choose all `samples/...` files
   (up to 12 at a time: do the 9 emergency pictures first, then the 6 ordinary).
3. Tick **Also detect emergency vehicles** and press **Analyze images**.

**Expected output**

| Pictures | Expected |
|---|---|
| `ambulance_*`, `fire_truck_*`, `police_car_*` (9) | Each gets an orange box labelled with its class and a **Priority request (simulated)** tag. The "Emergency vehicles" tile counts them. |
| `ordinary_*` (6) | Green boxes on cars/vans, **no** emergency tag. |
| Summary table and CSV | One row per picture: vehicles, breakdown, emergency count, seconds. |

Box colours everywhere: **green** = vehicle, **red** = vehicle that broke a rule,
**orange (thick)** = emergency vehicle.

How to read it: these pictures come from the model's training data, so passing
only proves the app works. Missing one of the 9 is a small problem; flagging an
`ordinary_*` picture is a false alarm and worth noting.

## B. Demo video (known answers for every check)

1. Analyze footage > **Video**, choose `videos/demo_all_checks.mp4` in "Or pick a
   video already in the project".
2. An **Expected results** box appears. Press **Apply the demo settings** (signal
   cycle 6 s red / 6 s green, stop line 60%, speed lines 45% / 75% with 10 m
   between them and a 40 km/h limit, wrong way "down", collisions on, emergency
   on if the model is installed).
3. Press **Run analysis** (about 30 seconds of video; a CPU takes a few minutes).

**Expected output**

| Where | What |
|---|---|
| Result tiles | Violations **3**, Possible collisions **1**, Emergency vehicles **3** (0 without the model) |
| Violations tab | red light at about 2.5 s, speeding at about 9.9 s (45 km/h), wrong way at about 12.8 s |
| Collisions tab | one entry at about 20 s, with the banner "POSSIBLE COLLISION - VERIFY" on that frame |
| Emergency tab | ambulance, fire truck and police car around 13.5 s, 19.8 s and 25.8 s |
| Annotated video | red stop line while the signal is red (green when green), amber speed lines, red boxes on flagged cars, the banner "Signal: RED (simulated)" |
| The van at 8 s | **no** violation (it crosses on green: that is correct) |

Then open **Evidence**: each violation shows the full frame and a cropped photo,
with status *pending*. Approve or reject a few to see the review flow, and open
**Dashboard** to see the counts and the "waiting for review" notice.

You can compare automatically:

```bash
python scripts/evaluate.py --video data/videos/demo_all_checks.mp4 \
  --truth data/videos/demo_all_checks_truth.csv --signal cycle \
  --red-seconds 6 --green-seconds 6 --speed --distance-m 10 --speed-limit 40 \
  --wrong-way --direction down --collisions
```

Times within about a second count as a match. If counts differ, the cause is
the detector or tracker on this synthetic video (not the rules): for example a
track ID changing mid-pass can hide or duplicate an event.

## C. Your own photos

1. Copy photos into `data/my_media/` (or drag them into the uploader).
2. Images tab, pick them, leave confidence at 0.35, press **Analyze images**.

**What good looks like**

* Cars, motorcycles, buses and trucks have green boxes; counts look about right
  when you count by eye.
* Emergency tags appear only on real emergency vehicles.

**What to write down** (per photo): vehicles you can see, vehicles boxed,
emergency tag yes/no and whether it is correct. Move the **confidence** slider
down to find more vehicles (more false hits) or up to remove false hits.
Typical weak spots: small or distant vehicles, night, rain, heavy occlusion,
photos that are not from a fixed road camera.

## D. Your own video

1. Copy the clip into `data/my_media/` (fixed camera, 10-60 seconds is best).
2. Video tab, pick it. The first frame is shown with your lines.
3. **Calibrate** by dragging the sliders until the lines sit on the road:
   * **Stop line**: on the painted stop line.
   * **Signal**: either a simulated state (always red / green / cycle), or
     *Read from the traffic lamp* and box the lamp in percent of the frame.
   * **Speed**: two lines a known distance apart. Measure the real distance.
   * **Wrong way**: choose the normal direction and shade only your side of a
     two-way road.
4. Choose **First 300 frames** for a quick test and press **Run analysis**.

**What good looks like**

* Annotated video: boxes follow vehicles with a steady `ID`, the stop line
  changes colour with the signal, and flagged vehicles turn red.
* Violations tab: every row is a vehicle you can confirm broke the rule in the
  annotated video or the Evidence crop.
* With the signal set to *always red*, **every** vehicle that crosses the line
  is flagged. That is the setting working, not a fault; use *cycle* or the lamp
  reading to model a real signal.

**Judge it**

| Question | Good | Needs work |
|---|---|---|
| Did it flag what actually happened? | Matches what you saw | Misses (check the line position and the signal) |
| Did it flag things that did not happen? | Rare | Many: check line, signal setting, lane, direction |
| Do IDs stay on the same car? | Mostly | Frequent switches: lower traffic, higher resolution or a different angle |
| Speed plausible? | Within about 10% of a known speed | Wildly off: re-measure the line distance |
| Collisions | Each one is a real event or a near event | Several from overlapping boxes: treat as "verify" only |
| Processing speed tile | Real time on a GPU | A few FPS on a CPU is normal |

Then open **Evidence**, review each violation (approve or reject), and open
**Dashboard** to see totals. Records and images are saved unless you untick
"Save results to the database".

## E. Many clips at once (accuracy numbers)

```bash
python scripts/footage_report.py --normal clips/normal --emergency clips/emergency
```

This reports emergency false alarms per hour and the hit rate. See
[EVALUATION.md](EVALUATION.md) for how to record the numbers.

## If the output looks wrong

| You see | Likely cause |
|---|---|
| No vehicles at all | Wrong file, very small vehicles, or the detector is missing: run `python scripts/check_setup.py --full` |
| Everything flagged red-light | Signal is set to *always red*, or the stop line is above the whole road |
| Nothing flagged | Signal is green, or the stop line is below where vehicles stop |
| Speeds absurd | Wrong distance between the speed lines, or lines not on the same lane |
| Emergency tag on an ordinary vehicle | A false alarm: note it, and see [TRAINING.md](TRAINING.md) |
| Video will not play in the browser | Install ffmpeg (`pip install imageio-ffmpeg`); you can still download it |

More in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
