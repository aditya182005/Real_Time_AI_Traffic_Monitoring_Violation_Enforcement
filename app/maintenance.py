"""Daily upkeep for a deployed server: check, purge, back up.

    python -m app.maintenance --once          # run now
    python -m app.maintenance --loop          # run now, then every 24 hours

One run does, in this order:

1. **Integrity check** of the sealed violation records. The head hash and the
   result are appended to ``<backup dir>/integrity-heads.log``; keep a copy of
   that line somewhere off the server (see docs/PRODUCTION.md).
2. **Retention**: removes old evidence and plate text
   (``EVIDENCE_RETENTION_DAYS``) and old upload folders
   (``UPLOAD_RETENTION_DAYS``).
3. **Backup**: one ``traffic-data-<time>.tgz`` with a consistent copy of the
   database, the evidence and output files and ``users.json``; the newest
   ``BACKUP_KEEP`` (default 7) are kept.

The backup folder is ``BACKUP_DIR`` (default ``<data dir>/backups``). Point it
at a different disk, and copy it off the machine as well: a backup on the same
disk does not survive that disk failing.

The exit status is 1 if the integrity check found a problem.
"""

import argparse
import os
import re
import sqlite3
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app import housekeeping, integrity, paths, privacy

ARCHIVE = re.compile(r"^traffic-data-\d{8}-\d{6}\.tgz$")
DEFAULT_KEEP = 7
DEFAULT_EVERY_HOURS = 24


def backup_dir():
    configured = os.getenv("BACKUP_DIR", "").strip()

    return Path(configured).expanduser() if configured else paths.DATA_DIR / "backups"


def keep_count():
    try:
        return max(1, int(os.getenv("BACKUP_KEEP", DEFAULT_KEEP)))
    except ValueError:
        return DEFAULT_KEEP


def snapshot_database(target, source=None):
    """Copy the live database to ``target`` safely (works while it is in use)."""

    source = Path(source or paths.DB_PATH)

    with closing(sqlite3.connect(str(source))) as src, \
            closing(sqlite3.connect(str(target))) as dst:
        src.backup(dst)


def _stamp(now):
    return now.strftime("%Y%m%d-%H%M%S")


def make_backup(dest=None, keep=None, include_outputs=True, now=None):
    """Write a backup archive and prune old ones. Returns its path (or None)."""

    dest = Path(dest or backup_dir())
    dest.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    archive = dest / f"traffic-data-{_stamp(now)}.tgz"
    database = Path(paths.DB_PATH)
    users = Path(paths.DATA_DIR) / "users.json"
    outputs = Path(paths.OUTPUT_DIR)

    if not database.exists() and not outputs.exists():
        return None

    with tempfile.TemporaryDirectory() as tmp:
        partial = dest / (archive.name + ".partial")

        with tarfile.open(partial, "w:gz") as tar:
            if database.exists():
                copy = Path(tmp) / database.name
                snapshot_database(copy, database)
                tar.add(copy, arcname=database.name)

            if users.exists():
                tar.add(users, arcname=users.name)

            if include_outputs and outputs.is_dir():
                tar.add(outputs, arcname="outputs",
                        filter=lambda info: None if _inside(info.name, "uploads/_staging")
                        else info)

        os.replace(partial, archive)

    prune(dest, keep or keep_count())

    return archive


def _inside(name, folder):
    return f"/{folder}" in "/" + name


def prune(dest, keep):
    """Delete all but the newest ``keep`` backup archives; returns the removed."""

    archives = sorted(p for p in Path(dest).iterdir() if ARCHIVE.match(p.name))
    removed = archives[:-keep] if len(archives) > keep else []

    for old in removed:
        old.unlink(missing_ok=True)

    return removed


def check_integrity(log_dir=None, now=None):
    """Verify the record chain and append its head hash to the log."""

    now = now or datetime.now(timezone.utc)

    if not Path(paths.DB_PATH).exists():
        return {"records": 0, "sealed": 0, "problems": [], "warnings": [], "head": ""}

    with closing(sqlite3.connect(str(paths.DB_PATH))) as conn:
        result = integrity.verify(conn)

    log_dir = Path(log_dir or backup_dir())
    log_dir.mkdir(parents=True, exist_ok=True)

    with open(log_dir / "integrity-heads.log", "a", encoding="utf-8") as log:
        log.write(f"{now.isoformat(timespec='seconds')} "
                  f"head={result['head'] or '-'} sealed={result['sealed']} "
                  f"problems={len(result['problems'])}\n")

    return result


def run_once(include_outputs=True, now=None):
    """One full maintenance pass. Returns a summary dict."""

    summary = {"problems": [], "purged": {}, "runs_removed": 0, "backup": None}
    result = check_integrity(now=now)
    summary["problems"] = result["problems"]
    summary["head"] = result["head"]
    summary["sealed"] = result["sealed"]

    days = privacy.retention_days()

    if days > 0:
        summary["purged"] = privacy.purge_old(days)

    uploads = Path(paths.OUTPUT_DIR) / "uploads"
    housekeeping.cleanup_staging(uploads)
    summary["runs_removed"] = len(housekeeping.cleanup_old_runs(
        uploads, housekeeping.retention_days()))
    archive = make_backup(include_outputs=include_outputs, now=now)
    summary["backup"] = str(archive) if archive else None

    return summary


def describe(summary):
    lines = [f"Integrity: {summary['sealed']} sealed record(s), head "
             f"{(summary.get('head') or '-')[:12]}, "
             + ("OK" if not summary["problems"] else
                f"{len(summary['problems'])} PROBLEM(S)")]

    for record_id, kind, detail in summary["problems"]:
        lines.append(f"  PROBLEM record {record_id}: {kind}: {detail}")

    if summary["purged"]:
        lines.append(f"Retention: {summary['purged']['records']} record(s), "
                     f"{summary['purged']['files']} file(s) cleaned")

    lines.append(f"Old upload folders removed: {summary['runs_removed']}")
    lines.append(f"Backup: {summary['backup'] or 'nothing to back up yet'}")

    return "\n".join(lines)


def main(argv=None, sleep=time.sleep):
    parser = argparse.ArgumentParser(
        prog="python -m app.maintenance", description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="run now and exit")
    mode.add_argument("--loop", action="store_true",
                      help="run now, then repeat (for a container)")
    parser.add_argument("--every-hours", type=float, default=DEFAULT_EVERY_HOURS)
    parser.add_argument("--no-outputs", action="store_true",
                        help="back up the database only (not evidence files)")
    parser.add_argument("--max-runs", type=int, default=None,
                        help=argparse.SUPPRESS)       # for tests
    args = parser.parse_args(argv)
    status, runs = 0, 0

    while True:
        runs += 1

        try:
            summary = run_once(include_outputs=not args.no_outputs)
            print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}] maintenance")
            print(describe(summary), flush=True)

            if summary["problems"]:
                status = 1
        except Exception as exc:    # one bad night must not stop the loop
            print(f"maintenance failed: {type(exc).__name__}: {exc}", flush=True)
            status = 1

        if args.once or (args.max_runs and runs >= args.max_runs):
            return status

        sleep(args.every_hours * 3600)


if __name__ == "__main__":
    sys.exit(main())
