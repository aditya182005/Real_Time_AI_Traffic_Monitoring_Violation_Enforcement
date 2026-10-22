import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app import fines, integrity, paths

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = paths.DB_PATH

# Demo amounts (the defaults in app/fines.py). Set FINES_FILE to use your own.
RED_LIGHT_FINE = 1000
WRONG_WAY_FINE = 1500
BASE_SPEED_FINE = 500
EXTRA_SPEED_FINE_PER_10_KMH = 100


def _connect():
    # DB_PATH is looked up at call time so tests can point it elsewhere.
    return closing(sqlite3.connect(DB_PATH))


# Columns added after the first release; migrated into existing databases.
EXTRA_COLUMNS = {
    "violation_records": {
        "source": "TEXT",
        "crop_path": "TEXT",
        "camera_id": "TEXT",
        "plate_text": "TEXT",
        "plate_confidence": "REAL",
        # Human review (app/review.py)
        "review_status": "TEXT",
        "reviewed_by": "TEXT",
        "reviewed_at": "TEXT",
        "review_note": "TEXT",
        # Tamper evidence (app/integrity.py)
        "evidence_sha256": "TEXT",
        "crop_sha256": "TEXT",
        "model_version": "TEXT",
        "prev_hash": "TEXT",
        "record_hash": "TEXT",
    },
    "collision_events": {
        "alert_status": "TEXT",
        "camera_id": "TEXT",
        "source": "TEXT",
        "crop_path": "TEXT",
        "alert_latency_ms": "REAL",
    },
    "priority_events": {
        "camera_id": "TEXT",
        "source": "TEXT",
        "signal_override": "INTEGER",
    },
    "traffic_density": {
        "camera_id": "TEXT",
    },
}


def _ensure_columns(conn, table, columns):
    """Add any missing columns so older databases keep working."""

    existing = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})")
    }

    for name, sql_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def _create_table(conn):
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
            evidence_path TEXT,
            source TEXT,
            crop_path TEXT,
            camera_id TEXT,
            plate_text TEXT,
            plate_confidence REAL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS traffic_density (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            video_second INTEGER NOT NULL,
            vehicle_count REAL NOT NULL,
            timestamp TEXT NOT NULL,
            camera_id TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS priority_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            vehicle_class TEXT NOT NULL,
            confidence REAL NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            camera_id TEXT,
            source TEXT,
            signal_override INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS collision_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id_1 INTEGER NOT NULL,
            track_id_2 INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            evidence_path TEXT NOT NULL,
            alert_status TEXT,
            camera_id TEXT,
            source TEXT,
            crop_path TEXT,
            alert_latency_ms REAL
        )
    """)

    for table, columns in EXTRA_COLUMNS.items():
        _ensure_columns(conn, table, columns)


def setup_database():
    with _connect() as conn:
        _create_table(conn)
        conn.commit()


def calculate_fine(violation_type, speed=None, speed_limit=None):
    table = fines.load()

    if violation_type == "red_light":
        return table["red_light"]

    if violation_type == "wrong_way":
        return table["wrong_way"]

    if violation_type == "speeding":
        if speed is None or speed_limit is None:
            raise ValueError("Speed and speed limit are required.")

        if speed <= speed_limit:
            return 0

        excess = speed - speed_limit
        extra_blocks = int((excess + 9.999999) // 10)

        return table["speeding"]["base"] + (
            extra_blocks * table["speeding"]["per_10_kmh"]
        )

    raise ValueError(f"Unknown violation type: {violation_type}")


def log_violation(
    event_key,
    track_id,
    violation_type,
    evidence_path,
    speed=None,
    speed_limit=None,
    signal_state=None,
    source=None,
    crop_path=None,
    camera_id=None,
    plate_text=None,
    plate_confidence=None,
):
    """Insert a violation. Returns True if a new row was written.

    The table is created on demand: previously callers such as the red-light
    and speed pipelines never called ``setup_database()`` and crashed with
    "no such table: violation_records" on the first violation.
    """

    fine = calculate_fine(
        violation_type,
        speed,
        speed_limit
    )

    if fine == 0:
        return False

    timestamp = datetime.now(timezone.utc).isoformat()
    evidence_path = str(evidence_path) if evidence_path else None
    crop_path = str(crop_path) if crop_path else None
    sealed = {
        "event_key": event_key,
        "track_id": int(track_id),
        "violation_type": violation_type,
        "measured_speed": speed,
        "speed_limit": speed_limit,
        "signal_state": signal_state,
        "fine_amount": fine,
        "timestamp": timestamp,
        "source": source,
        "camera_id": camera_id,
        "model_version": integrity.model_version(),
        "evidence_sha256": integrity.sha256_file(evidence_path),
        "crop_sha256": integrity.sha256_file(crop_path),
    }

    with _connect() as conn:
        _create_table(conn)

        # One writer at a time, so two records never share a predecessor.
        conn.execute("BEGIN IMMEDIATE")
        previous = integrity.last_hash(conn)

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
                evidence_path,
                source,
                crop_path,
                camera_id,
                plate_text,
                plate_confidence,
                review_status,
                model_version,
                evidence_sha256,
                crop_sha256,
                prev_hash,
                record_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'pending', ?, ?, ?, ?, ?)
        """, (
            event_key,
            int(track_id),
            violation_type,
            speed,
            speed_limit,
            signal_state,
            fine,
            timestamp,
            evidence_path,
            source,
            crop_path,
            camera_id,
            plate_text,
            plate_confidence,
            sealed["model_version"],
            sealed["evidence_sha256"],
            sealed["crop_sha256"],
            previous,
            integrity.chain_hash(previous, sealed),
        ))

        conn.commit()

        return cursor.rowcount == 1


def log_density_samples(source, samples, camera_id=None):
    """Store ``(video_second, avg_vehicle_count)`` samples for analytics."""

    if not samples:
        return 0

    timestamp = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        _create_table(conn)

        conn.executemany("""
            INSERT INTO traffic_density (
                source, video_second, vehicle_count, timestamp, camera_id
            )
            VALUES (?, ?, ?, ?, ?)
        """, [
            (source, int(second), float(count), timestamp, camera_id)
            for second, count in samples
        ])

        conn.commit()

    return len(samples)


def log_priority_event(
    vehicle_class,
    confidence,
    track_id=-1,
    camera_id=None,
    source=None,
    signal_override=True
):
    """Record a simulated emergency-priority request.

    ``track_id`` is -1 when the emergency detector is not tracked.
    ``signal_override`` records that the simulated signal was forced green.
    """

    with _connect() as conn:
        _create_table(conn)

        conn.execute("""
            INSERT INTO priority_events (
                track_id, vehicle_class, confidence,
                event_type, timestamp, camera_id, source, signal_override
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(track_id),
            vehicle_class,
            round(float(confidence), 3),
            "SIMULATED_PRIORITY_REQUEST",
            datetime.now(timezone.utc).isoformat(),
            camera_id,
            source,
            1 if signal_override else 0
        ))

        conn.commit()


def log_collision_event(
    track_id_1,
    track_id_2,
    evidence_path,
    camera_id=None,
    source=None,
    crop_path=None,
    alert_status="pending"
):
    """Insert a possible-collision record and return its row id."""

    with _connect() as conn:
        _create_table(conn)

        cursor = conn.execute("""
            INSERT INTO collision_events (
                track_id_1, track_id_2, event_type, timestamp,
                evidence_path, alert_status, camera_id, source, crop_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(track_id_1),
            int(track_id_2),
            "possible_collision",
            datetime.now(timezone.utc).isoformat(),
            str(evidence_path),
            alert_status,
            camera_id,
            source,
            str(crop_path) if crop_path else None
        ))

        conn.commit()

        return cursor.lastrowid


def set_alert_status(event_id, status, latency_ms=None):
    """Store the outcome of the Twilio alert on a collision record.

    ``latency_ms`` is the time from the collision being detected to Twilio
    accepting (or rejecting) the request.
    """

    with _connect() as conn:
        _create_table(conn)

        conn.execute(
            "UPDATE collision_events "
            "SET alert_status = ?, alert_latency_ms = ? WHERE id = ?",
            (
                status,
                None if latency_ms is None else round(float(latency_ms), 1),
                event_id,
            )
        )

        conn.commit()
