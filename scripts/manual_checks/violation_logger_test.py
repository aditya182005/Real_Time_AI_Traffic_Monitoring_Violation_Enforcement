"""Manual check: run from the project root, e.g.
    python scripts/manual_checks/violation_logger_test.py
Not part of the automated tests (see tests/)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import sqlite3

from app.violation.violation_logger import (
    setup_database,
    log_violation,
    DB_PATH
)

setup_database()

# Test a red-light violation.
inserted = log_violation(
    event_key="week6-test-red-001",
    track_id=101,
    violation_type="red_light",
    evidence_path="outputs/evidence/test_red.jpg",
    signal_state="RED"
)

print("Red-light record inserted:", inserted)

# Test a speeding violation.
inserted = log_violation(
    event_key="week6-test-speed-001",
    track_id=102,
    violation_type="speeding",
    evidence_path="outputs/evidence/test_speed.jpg",
    speed=65,
    speed_limit=40
)

print("Speeding record inserted:", inserted)

# Test duplicate prevention using the same event key.
duplicate = log_violation(
    event_key="week6-test-red-001",
    track_id=101,
    violation_type="red_light",
    evidence_path="outputs/evidence/test_red.jpg",
    signal_state="RED"
)

print("Duplicate inserted:", duplicate)

with sqlite3.connect(DB_PATH) as conn:
    rows = conn.execute("""
        SELECT event_key, track_id, violation_type,
               measured_speed, speed_limit, fine_amount
        FROM violation_records
        WHERE event_key LIKE 'week6-test-%'
        ORDER BY id
    """).fetchall()

    for row in rows:
        print(row)
