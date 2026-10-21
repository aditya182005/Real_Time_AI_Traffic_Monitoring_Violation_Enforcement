# Sample data for trying the system

## Pictures (`data/samples`)

| Files | What they are |
|---|---|
| `ambulance_1-3.jpg` | ambulances |
| `fire_truck_1-3.jpg` | fire trucks |
| `police_car_1-3.jpg` | police cars |
| `ordinary_1-6.jpg` | cars and vans that are **not** emergency vehicles (they should NOT be flagged) |

Upload them on **Analyze footage → Images** with *Also detect emergency
vehicles* ticked. The first 9 should be flagged, the 6 `ordinary_*` should not.

These come from the dataset the model was trained on, so good results here
show the app works, **not** that the model is accurate. For an honest test use
your own photos and footage.

## Demo video (`data/videos/demo_all_checks.mp4`)

30 seconds, every check fires once, in this order (times in seconds):

| Time | What happens | Check |
|---|---|---|
| 2.5 | a car crosses the stop line while the signal is red | red-light |
| 8.0 | a van crosses on green | none (correct) |
| 9.9 | a car goes through the speed lines at 45 km/h (limit 40) | speeding |
| 12.8 | a car drives up the screen against the traffic | wrong-way |
| 20.1 | a car hits a stopped van and stops dead | collision |
| 13.5, 19.8, 25.8 | ambulance, fire truck, police car appear | emergency |

Settings that make it work (the command line sets them; in the app use the
same values: signal *cycle* 6 s red / 6 s green, stop line 60%, speed lines
45% and 75% with 10 m between them and limit 40 km/h, wrong-way *down*,
collisions on, emergency vehicles on):

```
python run_video.py --input data/videos/demo_all_checks.mp4 --signal cycle --red-seconds 6 --green-seconds 6 --speed --distance-m 10 --speed-limit 40 --wrong-way --direction down --collisions --emergency
```

Score a real run against the expected events:

```
python evaluate.py --video data/videos/demo_all_checks.mp4 --truth data/videos/demo_all_checks_truth.csv --signal cycle --red-seconds 6 --green-seconds 6 --speed --distance-m 10 --speed-limit 40 --wrong-way --direction down --collisions
```

`demo_all_checks_truth.csv` is what the checks report when detection is
perfect (the script plays the scripted vehicle positions through the real
checks). Your model should match it; misses or extras mean the detector or
tracker struggled, not the rules. Emergency events are shown in the output
but not scored.

The video is made by `python make_demo_video.py` from the pictures above
(vehicles are photo patches driven across a plain road), so it is a pipeline
demo, not real traffic. The real YOLO and tracker on it have not been
checked by the author.

## Credit

Pictures: Roboflow Universe "ambulance-police-firetruck", version 4, by
detection-cars, licence CC BY 4.0:
https://universe.roboflow.com/detection-cars/ambulance-police-firetruck/dataset/4
The demo video is made from them and carries the same licence.
