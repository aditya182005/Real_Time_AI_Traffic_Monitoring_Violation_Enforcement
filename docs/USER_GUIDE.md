# User guide

## Starting

```bash
streamlit run app/main.py
```

Open the address Streamlit prints (usually http://localhost:8501). If sign-in
is configured you will see a login first.

## Roles

| Role | Can do |
|---|---|
| viewer | Look at the dashboard, evidence and alerts. |
| operator | Everything a viewer can, plus analyze footage and start live cameras. |
| admin | Everything, plus the Admin page (users, audit log, housekeeping). |

On your own computer with no password set, you are signed in as admin.
Manage accounts with `python -m app.users add NAME --role admin`.

## Pages

| Group | Page | Use it to |
|---|---|---|
| Overview | Dashboard | See totals, trends, violation types and recent records, filtered by date range and camera. |
| Monitor | Analyze footage | Upload a video, choose signal and speed settings, and run the analysis. |
| Monitor | Live camera | Start an RTSP, webcam or file stream configured in `LIVE_CAMERAS`. |
| Review | Evidence | Browse saved frames and vehicle crops with plate text where read. |
| Review | Alerts | See collision alerts, Twilio delivery status and latency. |
| System | About | Version, configuration status and health. |
| System | Admin | System status, audit log, accounts, record integrity check (admins only). |

## Common tasks

**Analyze a video.** Analyze footage, upload a file (try
`data/samples/demo_traffic.mp4`, see [the sample README](../data/samples/README.md)),
set the stop-line position and signal, tick speed, wrong-way, collision or
emergency checks, press run. Results appear on the Dashboard and Evidence pages.

**Review violations.** Every violation starts as *pending*. On the Evidence page,
choose an event, look at the frame and crop, add a note if useful, and press
Approve or Reject (operators and admins). Use the *Show* filter to work through
pending items. The dashboard lists how many are waiting.

**Read the signal from the video.** On Analyze footage, choose *Read from the
traffic lamp* and enter the lamp's box in percent of the frame (from the
command line: `--signal lamp --lamp-roi 82,4,90,22`). Red lit means RED, green
or amber means GREEN. Check the first seconds by eye.

**Use a saved camera setup.** Put each camera's calibration in the file named by
`CAMERAS_FILE` and run `python scripts/run_video.py --profile NAME` (see
`deploy/cameras.example.json`).

**Check records and privacy.** `python -m app.integrity verify` detects altered
records. `python -m app.privacy purge|export-plate|erase-plate` handles
retention and data requests. See [PRODUCTION.md](PRODUCTION.md).

**Calibrate speed.** Speed needs two lines a known distance apart. Set the
line positions and the real distance in metres; the estimate is only as good
as that measurement.

**Run from the command line.**

```bash
python scripts/run_video.py data/videos/traffic.mp4 --no-display --max-frames 300
python scripts/evaluate.py --video clip.mp4 --truth truth.csv --speed --collisions
```

`--max-frames` is handy on a CPU-only machine.

**Receive alerts.** Configure Twilio ([CONFIGURATION.md](CONFIGURATION.md)),
then test with `python -m app.alerts.twilio_alert --send`.

## Fines

Default fines are illustrative: red light 1000, wrong way 1500, speeding 500 plus
100 per 10 km/h over the limit. Set `FINES_FILE` to use your own amounts (`app/fines.py`). Every record
should be reviewed by a person before any real-world use.
