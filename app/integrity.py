"""Tamper-evident violation records.

Each violation is stored with the SHA-256 of its evidence image and crop, the
model version that produced it, and a hash that also covers the previous
record (a chain, like a ledger). Editing a stored field, swapping an evidence
image, or deleting a record from the middle changes a hash, and
``python -m app.integrity verify`` reports it.

What this does NOT do: someone who can rewrite the whole database and
recompute every hash can still forge it, and deleting the newest records
leaves no trace. To close that gap, copy the "head" hash printed by ``verify``
somewhere outside this server (an email to yourself, a ticket) after each
review session; a later ``verify --expect HEAD`` then proves nothing before
that point changed.

Review decisions and plate text are deliberately outside the chain: they are
meant to change (a reviewer approves, a privacy purge removes a plate), and
review changes are written to the audit log instead.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from app import paths

ROOT = Path(__file__).resolve().parents[1]

# The fields the chain covers, in order.
FIELDS = (
    "event_key", "track_id", "violation_type", "measured_speed",
    "speed_limit", "signal_state", "fine_amount", "timestamp", "source",
    "camera_id", "model_version", "evidence_sha256", "crop_sha256",
)
_FLOATS = {"measured_speed", "speed_limit"}
_INTS = {"track_id", "fine_amount"}


def sha256_file(path):
    """Hex digest of a file, or None if it is missing."""

    if not path:
        return None

    file = Path(str(path))

    if not file.is_absolute():
        file = ROOT / file

    try:
        digest = hashlib.sha256()

        with open(file, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)

        return digest.hexdigest()
    except OSError:
        return None


def _normal(name, value):
    """Same text whether a value was just computed or read back from SQLite."""

    if value is None:
        return None

    if name in _FLOATS:
        return repr(float(value))

    if name in _INTS:
        return int(value)

    return str(value)


def chain_hash(previous, values):
    payload = json.dumps(
        [_normal(name, values.get(name)) for name in FIELDS],
        separators=(",", ":"), ensure_ascii=True)

    return hashlib.sha256(
        f"{previous or ''}|{payload}".encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def model_version():
    """A short label for the models in use, stored with every record.

    Set ``MODEL_VERSION`` to your own label (for example a release tag).
    Otherwise it is built from the weights: the vehicle model name and the
    first 12 characters of the emergency model's SHA-256.
    """

    configured = os.getenv("MODEL_VERSION", "").strip()

    if configured:
        return configured[:64]

    emergency = sha256_file(ROOT / "models" / "emergency_vehicle.pt")

    return "yolov8n+emergency:" + (emergency[:12] if emergency else "none")


def last_hash(conn):
    row = conn.execute(
        "SELECT record_hash FROM violation_records "
        "WHERE record_hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()

    return row[0] if row else ""


def verify(conn, check_files=True):
    """Check every sealed record. Returns a dict (see keys below).

    ``problems`` means something was changed; ``warnings`` means an evidence
    file is gone (for example removed by the retention setting), which is not
    proof of tampering.
    """

    conn.row_factory = sqlite3.Row
    columns = {r[1] for r in conn.execute("PRAGMA table_info(violation_records)")}

    if "record_hash" not in columns:
        return {"records": 0, "sealed": 0, "unsealed": 0,
                "problems": [], "warnings": [], "head": ""}

    rows = conn.execute(
        "SELECT * FROM violation_records ORDER BY id").fetchall()
    problems, warnings = [], []
    previous, sealed = "", 0

    for row in rows:
        if not row["record_hash"]:
            continue

        sealed += 1
        values = dict(row)

        if (row["prev_hash"] or "") != previous:
            problems.append((row["id"], "chain_broken",
                             "a record before this one was removed or changed"))

        if chain_hash(row["prev_hash"], values) != row["record_hash"]:
            problems.append((row["id"], "record_changed",
                             "stored fields no longer match their hash"))

        if check_files:
            for label, path_col, hash_col in (
                    ("evidence", "evidence_path", "evidence_sha256"),
                    ("crop", "crop_path", "crop_sha256")):
                if not row[hash_col]:
                    continue

                actual = sha256_file(row[path_col])

                if actual is None:
                    warnings.append((row["id"], f"{label}_missing",
                                     f"{row[path_col]} not found"))
                elif actual != row[hash_col]:
                    problems.append((row["id"], f"{label}_changed",
                                     f"{row[path_col]} differs from when it was saved"))

        previous = row["record_hash"]

    return {"records": len(rows), "sealed": sealed,
            "unsealed": len(rows) - sealed,
            "problems": problems, "warnings": warnings, "head": previous}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m app.integrity",
        description="Check that stored violation records were not altered.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify", help="verify the record chain")
    check.add_argument("--no-files", action="store_true",
                       help="skip re-hashing evidence images")
    check.add_argument("--expect", metavar="HEAD",
                       help="a head hash you saved earlier; it must still "
                            "appear in the chain")
    args = parser.parse_args(argv)

    if not paths.DB_PATH.exists():
        print("No database yet.")
        return 0

    with closing(sqlite3.connect(str(paths.DB_PATH))) as conn:
        result = verify(conn, check_files=not args.no_files)
        known = {r[0] for r in conn.execute(
            "SELECT record_hash FROM violation_records "
            "WHERE record_hash IS NOT NULL")} if result["sealed"] else set()

    print(f"Records: {result['records']}  sealed: {result['sealed']}  "
          f"not sealed (older records): {result['unsealed']}")

    for record_id, kind, detail in result["problems"]:
        print(f"PROBLEM  record {record_id}: {kind}: {detail}")

    for record_id, kind, detail in result["warnings"]:
        print(f"warning  record {record_id}: {kind}: {detail}")

    if args.expect and args.expect not in known:
        print(f"PROBLEM  the saved head {args.expect[:12]}... is not in the "
              "chain: records were removed or rewritten.")
        result["problems"].append((None, "head_missing", args.expect))

    print(f"Head hash: {result['head'] or '(none)'}")
    print("Save the head hash somewhere outside this server.")
    print("OK" if not result["problems"] else "FAILED")

    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
