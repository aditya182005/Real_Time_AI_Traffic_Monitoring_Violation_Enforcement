"""E-challan: a one-page PDF notice for a violation a person has approved.

    python -m app.challan --id 12            # one record
    python -m app.challan --all-approved     # every approved record

The PDF shows the violation, the fine from the fine table, the plate if one
was read, the evidence picture and the crop, who approved it, and the
integrity hash of the record. A challan can only be made for an *approved*
record: the review step is what stops the model's guesses becoming notices.

It is a **demonstration document**. Making it a legal notice needs the
authority that has the power to fine, their form, and their fine schedule;
the footer says so on every page.
"""

import argparse
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app import audit, paths, pdfmini

NAMES = {
    "red_light": "Red light violation",
    "speeding": "Speeding",
    "wrong_way": "Driving the wrong way",
    "no_helmet": "Rider without a helmet",
}
FOOTER = (
    "DEMONSTRATION DOCUMENT. Produced from an automated detection that a",
    "person reviewed. It is not a legal notice: that needs the authority",
    "that has the power to fine, on its own form and fine schedule.",
)
ROOT = Path(__file__).resolve().parents[1]


class ChallanError(ValueError):
    """The challan cannot be made (unknown or unapproved record)."""


def challan_number(record):
    stamp = re.sub(r"\D", "", str(record.get("timestamp") or ""))[:8] or "00000000"

    return f"TA-{stamp}-{int(record['id']):06d}"


def fetch_record(record_id, db_path=None):
    db_path = Path(db_path or paths.DB_PATH)

    if not db_path.exists():
        raise ChallanError("There is no database yet.")

    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row

        try:
            row = conn.execute("SELECT * FROM violation_records WHERE id = ?",
                               (int(record_id),)).fetchone()
        except sqlite3.Error as exc:
            raise ChallanError(f"Could not read the record: {exc}") from exc

    if row is None:
        raise ChallanError(f"No violation record with id {record_id}.")

    return dict(row)


def _safe_file(value):
    """A picture path from the database, only if it is inside the data folders."""

    if not value:
        return None

    path = Path(str(value))

    if not path.is_absolute():
        path = ROOT / path

    try:
        path = path.resolve()
    except OSError:
        return None

    if not any(path.is_relative_to(root.resolve())
               for root in paths.ALLOWED_EVIDENCE_ROOTS):
        return None

    return path if path.is_file() else None


def _jpeg(value):
    file = _safe_file(value)

    if file is None:
        return None

    try:
        data = file.read_bytes()
        pdfmini.jpeg_info(data)

        return data
    except (OSError, pdfmini.PdfError):
        return None


def _short(value, limit=78):
    text = "" if value is None else str(value)

    return text if len(text) <= limit else text[:limit - 3] + "..."


def build_pdf(record):
    """The challan as PDF bytes (does not check approval; ``create`` does)."""

    number = challan_number(record)
    kind = record.get("violation_type")
    doc = pdfmini.Document(title=f"Traffic violation notice {number}",
                           author="Traffic Agent")
    page = doc.add_page()
    left, right = 40, 555

    page.rect(left, 770, right - left, 52, fill=0.92, gray=0.6)
    page.text(left + 12, 798, "TRAFFIC VIOLATION NOTICE", 18, "bold")
    page.text(left + 12, 781, "Demonstration document - not a legal notice",
              9, gray=0.35)
    page.text(right - 150, 798, number, 11, "mono")

    rows = [
        ("Violation", NAMES.get(kind, str(kind).replace("_", " ").title())),
        ("Date and time (UTC)", str(record.get("timestamp") or "")[:19]
         .replace("T", " ")),
        ("Camera", _short(record.get("camera_id") or "-")),
        ("Source", _short(record.get("source") or "-")),
        ("Vehicle track ID", record.get("track_id", "-")),
    ]

    plate = record.get("plate_text")
    rows.append(("Number plate",
                 f"{plate} (read automatically, verify)" if plate
                 else "not read"))

    if kind == "speeding":
        rows.append(("Measured speed",
                     f"{float(record['measured_speed']):.0f} km/h in a "
                     f"{float(record['speed_limit']):.0f} km/h limit"
                     if record.get("measured_speed") is not None
                     and record.get("speed_limit") is not None else "-"))

    if kind == "red_light":
        rows.append(("Signal state", record.get("signal_state") or "-"))

    rows.append(("Fine", f"Rs. {int(record.get('fine_amount') or 0):,}"))
    y = 740

    for label, value in rows:
        page.text(left, y, label, 10, "bold", gray=0.25)
        page.text(left + 150, y, value, 11,
                  "bold" if label == "Fine" else "regular")
        page.line(left, y - 6, right, y - 6, 0.3, 0.8)
        y -= 22

    frame, crop = _jpeg(record.get("evidence_path")), _jpeg(record.get("crop_path"))
    top = y - 6
    page.text(left, top, "Evidence", 10, "bold", gray=0.25)
    shown = False

    if frame:
        w, h = page.jpeg(frame, left, top - 8 - 220, 330, 220)
        shown = True

    if crop:
        page.jpeg(crop, left + 345, top - 8 - 220, 170, 220)
        shown = True

    if not shown:
        page.text(left, top - 22, "The evidence pictures are no longer "
                  "available (removed by the retention setting).", 9,
                  gray=0.35)

    y = top - 250
    page.text(left, y, "Review", 10, "bold", gray=0.25)
    reviewer = record.get("reviewed_by") or "-"
    when = str(record.get("reviewed_at") or "")[:19].replace("T", " ")
    page.text(left + 150, y, f"{record.get('review_status') or 'pending'} by "
              f"{reviewer} {when}".strip(), 10)

    if record.get("review_note"):
        y -= 16
        page.text(left + 150, y, _short(record["review_note"]), 9, gray=0.3)

    y -= 20
    page.text(left, y, "Record seal", 10, "bold", gray=0.25)
    page.text(left + 150, y, _short(record.get("record_hash") or "not sealed",
                                    40), 9, "mono")
    y -= 16
    page.text(left, y, "Model", 10, "bold", gray=0.25)
    page.text(left + 150, y, _short(record.get("model_version") or "-", 60), 9)

    page.line(left, 90, right, 90, 0.5, 0.5)

    for number_, text in enumerate(FOOTER):
        page.text(left, 76 - 12 * number_, text, 8, gray=0.35)

    return doc.render()


def create(record_id, out_dir=None, require_approved=True, db_path=None,
           user=None, role=None):
    """Write the challan PDF and return its path."""

    record = fetch_record(record_id, db_path)

    if require_approved and record.get("review_status") != "approved":
        raise ChallanError(
            f"Record {record_id} is {record.get('review_status') or 'pending'}"
            ": only approved violations get a challan. Approve it on the "
            "Evidence page first.")

    out_dir = Path(out_dir or paths.OUTPUT_DIR / "challans")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{challan_number(record)}.pdf"
    target.write_bytes(build_pdf(record))
    audit.record("challan_created", user=user, role=role,
                 detail=f"record {int(record['id'])} -> {target.name}")

    return target


def approved_ids(db_path=None):
    db_path = Path(db_path or paths.DB_PATH)

    if not db_path.exists():
        return []

    with closing(sqlite3.connect(str(db_path))) as conn:
        try:
            return [r[0] for r in conn.execute(
                "SELECT id FROM violation_records "
                "WHERE review_status = 'approved' ORDER BY id")]
        except sqlite3.Error:
            return []


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m app.challan", description=__doc__.split("\n")[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--id", type=int, help="violation record id")
    which.add_argument("--all-approved", action="store_true")
    parser.add_argument("--output", default=None, help="folder for the PDFs")
    args = parser.parse_args(argv)
    ids = [args.id] if args.id else approved_ids()

    if not ids:
        print("No approved violations. Approve some on the Evidence page.")
        return 1

    failed = 0

    for record_id in ids:
        try:
            print(create(record_id, args.output, user="cli"))
        except ChallanError as exc:
            failed += 1
            print(f"Record {record_id}: {exc}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
