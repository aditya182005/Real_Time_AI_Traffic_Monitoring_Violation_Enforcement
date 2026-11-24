"""A short daily summary, sent to Telegram with the record-chain head hash.

Sending the head hash somewhere off the server is what lets you prove later
that nothing before it changed (see app/integrity.py). This does that step
automatically; the maintenance job calls it once per pass.

    python -m app.digest            # print the digest
    python -m app.digest --send     # also send it to Telegram

Set ``DIGEST=off`` to switch it off. It sends only counts and the hash: no
plates, pictures or locations.
"""

import argparse
import os
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone

from app import integrity, paths
from app.alerts import telegram_alert


def enabled():
    return os.getenv("DIGEST", "").strip().lower() != "off"


def _rows(conn, table, since):
    try:
        return conn.execute(
            f"SELECT * FROM {table} WHERE timestamp >= ?", (since,)).fetchall()
    except sqlite3.Error:
        return []


def build(hours=24, now=None, db_path=None):
    """The digest text for the last ``hours`` hours."""

    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).isoformat()
    db_path = db_path or paths.DB_PATH
    lines = [f"Traffic Agent daily digest, {now.strftime('%d %b %Y %H:%M UTC')}",
             f"Last {hours} hours:"]

    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error:
        return "\n".join(lines + ["  no database yet"])

    with closing(conn):
        conn.row_factory = sqlite3.Row
        violations = _rows(conn, "violation_records", since)
        collisions = _rows(conn, "collision_events", since)
        priority = _rows(conn, "priority_events", since)
        kinds = Counter(r["violation_type"] for r in violations)
        pending = sum(1 for r in violations
                      if (r["review_status"] or "pending") == "pending")
        fines = sum((r["fine_amount"] or 0) for r in violations
                    if r["review_status"] == "approved")

        lines.append(f"  violations: {len(violations)}"
                     + (" (" + ", ".join(f"{k} {v}" for k, v in
                                         sorted(kinds.items())) + ")"
                        if kinds else ""))
        lines.append(f"  waiting for review: {pending}")
        lines.append(f"  approved fines: Rs.{fines:,.0f}")
        lines.append(f"  possible collisions: {len(collisions)}")
        lines.append(f"  emergency priority requests: {len(priority)}")

        result = integrity.verify(conn)

    lines.append(f"Record chain: {result['sealed']} sealed, "
                 + ("OK" if not result["problems"]
                    else f"{len(result['problems'])} PROBLEM(S)"))
    lines.append(f"Head hash: {result['head'] or '-'}")
    lines.append("Keep this hash. `python -m app.integrity verify --expect "
                 "<hash>` later proves nothing before it changed.")

    return "\n".join(lines)


def send(text=None, sender=telegram_alert.send_alert, **options):
    """Send the digest. Returns a status text (never raises)."""

    if not enabled():
        return "off (DIGEST=off)"

    if not telegram_alert.is_configured() and sender is telegram_alert.send_alert:
        return telegram_alert.NOT_CONFIGURED

    try:
        return sender(text if text is not None else build(**options))
    except Exception as exc:    # a digest must never break maintenance
        return f"failed: {type(exc).__name__}"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.digest")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args(argv)
    text = build(hours=args.hours)
    print(text)

    if args.send:
        print(f"Telegram: {send(text)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
