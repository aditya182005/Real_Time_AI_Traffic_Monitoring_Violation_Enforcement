"""Privacy tools: keep personal data no longer than needed.

Evidence images and number plates are personal data. This module provides

* **retention**: ``EVIDENCE_RETENTION_DAYS`` (0 keeps everything). Older
  records lose their evidence images, crops and plate text; the row itself
  (type, time, camera, fine, review result) stays for statistics.
* **erasure**: remove everything stored for one plate on request.
* **export**: list everything stored for one plate (a subject-access request).

Command line::

    python -m app.privacy purge --days 90 [--dry-run]
    python -m app.privacy export-plate "KA01AB1234"
    python -m app.privacy erase-plate "KA01AB1234" [--dry-run]

The evidence hashes stay in the chain, so ``python -m app.integrity verify``
reports purged images as warnings (missing files), not as tampering.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import audit, paths

ROOT = Path(__file__).resolve().parents[1]


def retention_days():
    try:
        return max(0, int(os.getenv("EVIDENCE_RETENTION_DAYS", "0")))
    except ValueError:
        return 0


def normalise_plate(text):
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def _safe_delete(value):
    """Delete an evidence file, but only inside the allowed data folders."""

    if not value:
        return False

    path = Path(str(value))

    if not path.is_absolute():
        path = ROOT / path

    try:
        path = path.resolve()
    except OSError:
        return False

    if not any(path.is_relative_to(root.resolve())
               for root in paths.ALLOWED_EVIDENCE_ROOTS):
        return False

    try:
        path.unlink()
        return True
    except OSError:
        return False


def _has_table(conn):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='violation_records'"
    ).fetchone() is not None


def _scrub(conn, rows, dry_run):
    files = 0

    for row in rows:
        if not dry_run:
            files += _safe_delete(row["evidence_path"])
            files += _safe_delete(row["crop_path"])
            conn.execute(
                "UPDATE violation_records SET plate_text = NULL, "
                "plate_confidence = NULL WHERE id = ?", (row["id"],))
        else:
            files += sum(1 for k in ("evidence_path", "crop_path") if row[k])

    return files


def purge_old(days, now=None, dry_run=False, db_path=None):
    """Remove evidence and plate text older than ``days``. Returns counts."""

    db_path = db_path or paths.DB_PATH

    if days <= 0 or not Path(db_path).exists():
        return {"records": 0, "files": 0}

    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()

    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row

        if not _has_table(conn):
            return {"records": 0, "files": 0}

        rows = conn.execute(
            "SELECT id, evidence_path, crop_path FROM violation_records "
            "WHERE timestamp < ? AND (evidence_path IS NOT NULL "
            "OR crop_path IS NOT NULL OR plate_text IS NOT NULL)",
            (cutoff,)).fetchall()
        files = _scrub(conn, rows, dry_run)
        conn.commit()

    if rows and not dry_run:
        audit.record("privacy_purge", detail=f"older than {days} days: "
                     f"{len(rows)} records, {files} files")

    return {"records": len(rows), "files": files}


def _plate_rows(conn, plate):
    wanted = normalise_plate(plate)

    if not wanted:
        raise ValueError("Give a plate number.")

    return wanted, [
        row for row in conn.execute(
            "SELECT * FROM violation_records WHERE plate_text IS NOT NULL")
        if normalise_plate(row["plate_text"]) == wanted
    ]


def export_plate(plate, db_path=None):
    db_path = db_path or paths.DB_PATH

    if not Path(db_path).exists():
        return []

    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row

        if not _has_table(conn):
            return []

        _, rows = _plate_rows(conn, plate)

    return [dict(row) for row in rows]


def erase_plate(plate, dry_run=False, db_path=None):
    """Delete the images and plate text stored for one plate."""

    db_path = db_path or paths.DB_PATH

    if not Path(db_path).exists():
        return {"records": 0, "files": 0}

    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row

        if not _has_table(conn):
            return {"records": 0, "files": 0}

        wanted, rows = _plate_rows(conn, plate)
        files = _scrub(conn, rows, dry_run)
        conn.commit()

    if rows and not dry_run:
        # The plate itself is not written to the audit log.
        audit.record("privacy_erase_plate",
                     detail=f"{len(rows)} records, {files} files")

    return {"records": len(rows), "files": files}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m app.privacy", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    purge = sub.add_parser("purge", help="remove old evidence and plate text")
    purge.add_argument("--days", type=int, default=None,
                       help="default: EVIDENCE_RETENTION_DAYS")
    purge.add_argument("--dry-run", action="store_true")
    export = sub.add_parser("export-plate", help="print all data for a plate")
    export.add_argument("plate")
    erase = sub.add_parser("erase-plate", help="delete all data for a plate")
    erase.add_argument("plate")
    erase.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "purge":
        days = args.days if args.days is not None else retention_days()

        if days <= 0:
            print("Nothing to do: give --days N or set EVIDENCE_RETENTION_DAYS.")
            return 0

        result = purge_old(days, dry_run=args.dry_run)
        verb = "Would remove" if args.dry_run else "Removed"
        print(f"{verb} evidence for {result['records']} record(s), "
              f"{result['files']} file(s) older than {days} days.")
    elif args.command == "export-plate":
        print(json.dumps(export_plate(args.plate), indent=2, default=str))
    else:
        result = erase_plate(args.plate, dry_run=args.dry_run)
        verb = "Would erase" if args.dry_run else "Erased"
        print(f"{verb} {result['records']} record(s), {result['files']} file(s).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
