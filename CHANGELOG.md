# Changelog

## Unreleased

* Credibility and operations: `scripts/benchmark.py` (precision/recall with confidence intervals on your own clips, `docs/BENCHMARK.md`), `scripts/train_helmet.py`, click-to-calibrate speed (`scripts/calibrate_speed.py`, `--calibration`), zone violations (illegal parking, crossing encroachment, wrong lane, triple riding; `--zones`), traffic analytics (class counts, congestion by hour, heatmap), bulk review, evidence overlays, daily Telegram integrity digest, `--signal adaptive` driven by live queue counts, and emergency wait-time saved. See `docs/NEW_VIOLATIONS_AND_ANALYTICS.md`.

* Deployment readiness: the trained `models/emergency_vehicle.pt` is now in the repository; `docker compose --profile https up -d` adds HTTPS (Caddy, automatic certificate); a `maintenance` container runs `python -m app.maintenance` daily (integrity check with head-hash log, retention, backup with rotation); `scripts/check_setup.py --production` checks sign-in, `APP_ENV`, domain, retention, fines and backups; the dashboard port is published on `127.0.0.1` by default (`BIND_ADDRESS`); CI validates the compose files and runs the maintenance job.

* New: PDF e-challans for approved violations (`app/challan.py`, Evidence page button, CLI), Telegram alerts, no-helmet check (bring your own `models/helmet.pt`), adaptive signal timing simulator (`python -m app.signals.adaptive`), Arduino LED output (`--arduino-port`, `hardware/arduino_signal/`).

* Measured results for the retrained emergency model (test mAP@0.5 0.91; 1.0% of 400 held-out ordinary pictures flagged at confidence 0.65; 97.4% of real emergency pictures found).
* Fix for trucks flagged as fire trucks and cars as police cars: the bundled emergency dataset is removed; new Colab notebook trains on real-world datasets plus real street negatives (COCO, your own frames), checks for hidden emergency vehicles, and tests on held-out real pictures.
* New `--negatives` option in `build_emergency_dataset.py`, `fetch_coco_negatives.py`, `extract_frames.py`, `check_emergency_model.py --negatives`, and `EMERGENCY_CONFIDENCE`.
* Removed the CPU training workflow (use Colab).
* Analyze page can pick photos and videos from the project folder (`data/my_media`, `data/samples`, `data/videos`), shows the expected results for the demo video and can apply its settings.
* New `docs/CHECKING_OUTPUTS.md`.
* Human review of violations (pending / approved / rejected) with audit trail.
* Tamper-evident records: evidence hashes, model version and a hash chain;
  `python -m app.integrity verify` and an Admin check.
* Fine table from `FINES_FILE`; per-camera profiles from `CAMERAS_FILE`
  (`--profile`).
* Retention, plate export and erasure (`python -m app.privacy`,
  `EVIDENCE_RETENTION_DAYS`).
* Signal state read from the traffic lamp in the video (`--signal lamp`).
* New `docs/PRODUCTION.md`.

* Restructured the repository: tools moved to `scripts/`, deployment guide to `docs/DEPLOYMENT.md`.
* Company-style README and a documentation set under `docs/`.
* Added the MIT License.
* Added `scripts/footage_report.py` to batch-test real clips (false alarms per hour, emergency hit rate).
* Tidied the repository root: CLI tools now in `scripts/` (`python scripts/run_video.py`), extra requirements in `requirements/`.

## Earlier work

* Sample pictures and an all-checks demo video with a truth file (`data/samples/`).
* Emergency-vehicle dataset cleaning, training scripts, Colab notebooks, and a checker for false alarms.
* Roles, user accounts, audit log, live camera support, license-plate reading, Docker and CI.
* YOLOv8 + ByteTrack pipeline with red-light, speed, wrong-way and collision checks, Streamlit dashboard, Twilio alerts.
