# Measuring accuracy on your own footage

The numbers in the other docs come from public data or the demo video. This
tool gives you the number that matters: how often the system is right on
**your** road.

## 1. Collect clips

Put 5–10 clips (30 s – 5 min) in `clips/`. Include clips where nothing
happens: they are what exposes false alarms.

## 2. Write the truth by watching

`clips/truth.csv`, one row per real event:

```
clip,type,time_seconds
junction1.mp4,red_light,12.4
junction1.mp4,speeding,31.0
junction2.mp4,wrong_way,5.2
```

Types: `red_light`, `speeding`, `wrong_way`, `collision`, `no_helmet`,
`illegal_parking`, `crossing_encroachment`, `wrong_lane`, `triple_riding`.
A clip with no row must produce no detections.

## 3. Run

Options after `--` are the same ones you give `run_video.py`:

```
python scripts/benchmark.py --clips clips --truth clips/truth.csv \
    -- --signal cycle --speed --distance-m 12 --wrong-way
```

A detection is correct (TP) when the same clip has a truth row of the same
type within `--tolerance` seconds (default 3). Each truth row is used once.
Unmatched truth rows are misses (FN); unmatched detections are false alarms
(FP).

## 4. Read the report

Per type: TP, FP, FN, **precision**, **recall**, F1 and a 95% confidence
interval. With few events the interval is wide: that is honest, not a bug.
Quote the interval, not just the percentage, and say how many clips and events
it rests on. The report is also written to `--report` (default
`outputs/benchmark.md`).

## Calibrating speed

`python scripts/calibrate_speed.py --input clip.mp4 --width-m 3.5 --length-m 12`
opens a frame; click the four corners of a road rectangle whose size you know.
Run with `--calibration <file>` and speed uses real metres with perspective
handled. Accuracy depends on your clicking, flat road and a fixed camera.
