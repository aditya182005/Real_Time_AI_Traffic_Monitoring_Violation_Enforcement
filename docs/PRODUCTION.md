# Production readiness

What the software now does for a real deployment, what you must do yourself,
and what only an authority or partner can provide. For servers and HTTPS see
[DEPLOYMENT.md](DEPLOYMENT.md).

## Built into the software

| Need | Feature | How |
|---|---|---|
| A person decides, not the model | **Review**: every violation starts `pending`; operators and admins approve or reject on the Evidence page. Decisions go to the audit log. | Evidence page; the dashboard counts what is waiting |
| Records can be trusted | **Tamper evidence**: SHA-256 of each evidence image and crop, the model version, and a hash chain over all records | `python -m app.integrity verify`, or Admin > Record integrity |
| Your own fine amounts | **Fine table** from a JSON file | `FINES_FILE`, example in `deploy/fines.example.json` |
| Each camera is different | **Camera profiles**: stop line, speed lines, real distance, limit, direction, lamp area | `CAMERAS_FILE`, `--profile NAME`, example in `deploy/cameras.example.json` |
| Real signal state without a controller | **Lamp reading**: red/green read from the lamp in the video | `--signal lamp --lamp-roi X1,Y1,X2,Y2` or the Analyze page |
| Keep personal data no longer than needed | **Retention, export and erasure** of evidence images and plate text | `EVIDENCE_RETENTION_DAYS`, `python -m app.privacy ...` |
| Know which model flagged what | Model version stored on every record | `MODEL_VERSION` or derived from the weights |

### Routines to set up

1. **After each review session**, run `python -m app.integrity verify` and save
   the printed *head hash* somewhere off the server (email, ticket). Later,
   `verify --expect <hash>` proves nothing before that point was rewritten.
   Without an outside copy, someone who controls the server could rebuild the
   whole chain, and deleting only the newest records leaves no trace.
2. **Retention**: set `EVIDENCE_RETENTION_DAYS` and also run
   `python -m app.privacy purge` daily (cron or a scheduled task). The app
   purges only when it starts.
3. **Backups**: copy the data folder (`traffic_agent.db` and `outputs/`) to
   storage on another machine, and keep the saved head hashes with them.
4. **Fines**: write the amounts into a file under version control with a note of
   the rule they come from, and set `FINES_FILE`.

### Limits to know

* `approved` is a flag in this app. Nothing here sends a fine to anyone; an
  outside process must require `approved` before it acts.
* Lamp reading needs a clear, fixed view of the lamp and a hand-set box.
  Glare, night blooming or a tiny lamp will fool it. Check by eye.
* Review decisions and plate text are outside the hash chain on purpose
  (they must be changeable); review changes are in the audit log.
* SQLite handles one site well. Many busy cameras writing at once need a
  server database; that is not implemented.

## You still need to do

* Measure accuracy on your own footage ([EVALUATION.md](EVALUATION.md)) and
  fine-tune the models for your cameras ([TRAINING.md](TRAINING.md)).
* Measure the real distance between the speed lines on site and check speed
  against a reference vehicle.
* Run behind HTTPS with individual accounts ([DEPLOYMENT.md](DEPLOYMENT.md)).
* Run a trial in shadow mode: flag and review, issue nothing.

## Needs an authority or partner (not something software can do)

* Legal authority for automated enforcement and the official fine schedule.
* Reading the signal from the real controller, if the lamp reading is not enough.
* Connecting emergency priority to real signals (safety critical).
* A data protection assessment, privacy notice and retention rules for your
  jurisdiction.
* Ultralytics licence terms (AGPL-3.0) if this becomes a product or service.
