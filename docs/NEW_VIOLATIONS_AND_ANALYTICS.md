# New violations, analytics and operations

## Zone-based violations (`--zones zones.json`)

```json
{
  "no_parking": {"polygon": [[100,300],[400,300],[400,500],[100,500]], "seconds": 30},
  "crossing": {"y_top": 380, "y_bottom": 440},
  "restricted_lane": {"polygon": [[0,300],[200,300],[200,700],[0,700]], "allowed": ["motorcycle"]},
  "triple_riding": true
}
```

Points are pixels in the video frame. Run: `python scripts/run_video.py ... --zones zones.json`.

| Rule | Flags when | Fine (demo) |
|---|---|---|
| `illegal_parking` | a tracked vehicle stays in the polygon for `seconds` | 500 |
| `crossing_encroachment` | a vehicle stands on the crossing band while the signal is RED | 500 |
| `wrong_lane` | a class not in `allowed` stays in the lane polygon | 1000 |
| `triple_riding` | 3 or more heads on one motorcycle (needs the helmet model) | 1000 |

Every rule needs a tracked vehicle and a condition held for some time, so one
noisy frame cannot create a violation. Fines are demo values; set yours with
`FINES_FILE`. Phone-use and seatbelt checks are **not** included: they need a
trained model that does not exist here.

## Analytics

The Analytics page shows vehicles by class, congestion by hour (levels from
`CONGESTION_MODERATE` / `CONGESTION_HEAVY`, default 6 and 12 vehicles in
view), busiest and quietest hour, and a violation heatmap. Hours with no data
are left blank rather than called "Free".

## Review and evidence

* The Evidence page has bulk approve / reject.
* Evidence pictures can show *why* it was flagged: stop line, speed lines,
  trail and zone outlines.

## Daily digest

`python -m app.digest --send` (also run by the maintenance job) sends counts
and the record-chain head hash to Telegram, so a copy of the hash exists off
the server. `DIGEST=off` disables it. No plates or pictures are sent.

## Signal loop and emergency log

`--signal adaptive` makes the simulated signal's green time follow the queue
counted before the stop line (the other three approaches are modelled at fixed
arrival rates). It simulates the timing method; it does not control a real
signal. Emergency events record how long the ordinary signal would have kept
that approach red (`normal_wait_seconds`), when that can be known (not for a
lamp read from video or an adaptive signal).
