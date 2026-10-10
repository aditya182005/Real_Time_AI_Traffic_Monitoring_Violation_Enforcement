
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("traffic_agent.db")


def migrate_database(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS violation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            violation_type TEXT NOT NULL,
            signal_state TEXT NOT NULL DEFAULT 'RED',
            event_time TEXT NOT NULL,
            evidence_path TEXT
        )
    """)

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(violation)"
        ).fetchall()
    }

    if "signal_state" not in columns:
        conn.execute("""
            ALTER TABLE violation
            ADD COLUMN signal_state TEXT NOT NULL DEFAULT 'RED'
        """)

    conn.commit()


def save_violation(track_id, signal_state, evidence_path):
    with sqlite3.connect(DB_PATH) as conn:
        migrate_database(conn)

        conn.execute("""
            INSERT INTO violation (
                track_id,
                violation_type,
                signal_state,
                event_time,
                evidence_path
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            track_id,
            "RED_LIGHT",
            signal_state,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            str(evidence_path)
        ))

        conn.commit()
