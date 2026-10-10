
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "traffic_agent.db"

# Demo amounts only. Replace with applicable rules
# before using this in any real-world setting.
RED_LIGHT_FINE = 1000
BASE_SPEED_FINE = 500
EXTRA_SPEED_FINE_PER_10_KMH = 100


def setup_database():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS violation_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                track_id INTEGER NOT NULL,
                violation_type TEXT NOT NULL,
                measured_speed REAL,
                speed_limit REAL,
                signal_state TEXT,
                fine_amount INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                evidence_path TEXT
            )
        """)


def calculate_fine(violation_type, speed=None, speed_limit=None):
    if violation_type == "red_light":
        return RED_LIGHT_FINE

    if violation_type == "speeding":
        if speed is None or speed_limit is None:
            raise ValueError("Speed and speed limit are required.")

        if speed <= speed_limit:
            return 0

        excess = speed - speed_limit
        extra_blocks = int((excess + 9.999999) // 10)

        return BASE_SPEED_FINE + (
            extra_blocks * EXTRA_SPEED_FINE_PER_10_KMH
        )

    raise ValueError(f"Unknown violation type: {violation_type}")


def log_violation(
    event_key,
    track_id,
    violation_type,
    evidence_path,
    speed=None,
    speed_limit=None,
    signal_state=None
):
    fine = calculate_fine(
        violation_type,
        speed,
        speed_limit
    )

    if fine == 0:
        return False

    timestamp = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO violation_records (
                event_key,
                track_id,
                violation_type,
                measured_speed,
                speed_limit,
                signal_state,
                fine_amount,
                timestamp,
                evidence_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_key,
            int(track_id),
            violation_type,
            speed,
            speed_limit,
            signal_state,
            fine,
            timestamp,
            str(evidence_path) if evidence_path else None
        ))

        return cursor.rowcount == 1
