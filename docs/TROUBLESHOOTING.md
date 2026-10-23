# Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `requirements/plates.txt` / file not found | Your copy is older than the repo. Run `git pull`. |
| ByteTrack / `supervision` errors | The API changed. Reinstall pinned versions: `pip install -r requirements.txt` (`supervision>=0.20,<0.31`). |
| `openh264` messages when running `scripts/run_video.py` | Harmless codec notices from OpenCV. |
| `scripts/run_video.py` is very slow | CPU-only machines manage a few FPS. Use `--no-display` and `--max-frames 300`. Ctrl+C stops it. |
| `PermissionError` on the SQLite file (Windows) | Another process (a second Streamlit, a DB viewer) holds it. Close it and retry. |
| Twilio error 21608 | Trial account: the destination number must be verified in the Twilio Console. |
| No SMS, no error | Check all four `TWILIO_*`/`ALERT_TO_PHONE` values, then `python -m app.alerts.twilio_alert --send`. |
| Emergency vehicles never detected | `models/emergency_vehicle.pt` is missing. See [TRAINING.md](TRAINING.md); `python scripts/check_setup.py` reports it. |
| Trucks flagged as fire trucks, cars as police cars | The model never saw ordinary vehicles in real streets. Retrain with real negatives ([TRAINING.md](TRAINING.md)); meanwhile raise `EMERGENCY_CONFIDENCE` (for example 0.85). |
| Colab: "Only 0 training images were built" | None of the Roboflow sources downloaded. Check API key and that each source exists; read the printed per-source skips. |
| Colab: `Sample larger than population` | Same cause as above (no images). Fixed by the guard in the current notebook; `git pull` the branch it clones. |
| App refuses to start in production | `APP_ENV=production` needs sign-in: set `DASHBOARD_PASSWORD` or create users. See [DEPLOYMENT.md](DEPLOYMENT.md). |
| Live camera does not open | The address must be in `LIVE_CAMERAS` (or `LIVE_ALLOW_CUSTOM=true`) and reachable from the server. |
| Plates are blank | Install `requirements/plates.txt` and make sure `PLATE_OCR` is not `off`. |
| Import errors in tests | `pip install -r requirements/dev.txt` (or `requirements.txt`) and run `pytest` from the project root. |

Still stuck? Run `python scripts/check_setup.py` and include its output in an issue.
