"""Human review of violations.

Every violation starts as ``pending``. A person with the operator or admin
role approves or rejects it after looking at the evidence. Nothing in this
app issues a fine by itself; ``approved`` is the state an outside process
should require before acting on a record.

Decisions are stored on the record and written to the audit log.
"""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app import audit
from app.violation import violation_logger as vl

PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
STATUSES = (PENDING, APPROVED, REJECTED)
NOTE_LIMIT = 300


class ReviewError(ValueError):
    """The request cannot be applied (unknown record or status)."""


def status_of(value):
    """Records from before this feature have no status: they are pending."""

    return value if value in STATUSES else PENDING


def set_status(record_id, status, user, role=None, note="", address=None):
    """Approve or reject one violation. Returns the stored status."""

    if status not in (APPROVED, REJECTED, PENDING):
        raise ReviewError(f"Status must be one of: {', '.join(STATUSES)}.")

    if not user:
        raise ReviewError("A reviewer name is required.")

    note = audit.clean(note, NOTE_LIMIT)

    with closing(sqlite3.connect(str(vl.DB_PATH))) as conn:
        vl._create_table(conn)
        cursor = conn.execute(
            "UPDATE violation_records SET review_status = ?, reviewed_by = ?, "
            "reviewed_at = ?, review_note = ? WHERE id = ?",
            (status, user, datetime.now(timezone.utc).isoformat(),
             note or None, int(record_id)))
        conn.commit()

        if cursor.rowcount != 1:
            raise ReviewError(f"No violation record with id {record_id}.")

    audit.record(f"review_{status}", user=user, role=role,
                 detail=f"violation {int(record_id)}: {note}", address=address)

    return status


def counts(df):
    """{'pending': n, 'approved': n, 'rejected': n} for a violations frame."""

    result = {status: 0 for status in STATUSES}

    if df is None or df.empty:
        return result

    column = df["review_status"] if "review_status" in df.columns else None

    for value in (column if column is not None else [None] * len(df)):
        result[status_of(value)] += 1

    return result
