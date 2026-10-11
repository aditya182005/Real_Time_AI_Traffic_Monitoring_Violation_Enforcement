import sqlite3
from pathlib import Path

# Anchor the default to the project root. A bare relative name created a
# different traffic_agent.db depending on the directory you ran from, so the
# dashboard and the detection scripts could end up reading different files.
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "traffic_agent.db"


class Database:

    def __init__(self, db_name=DEFAULT_DB_PATH):
        self.connection = sqlite3.connect(str(db_name))

    def create_tables(self):

        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER,
                violation_type TEXT,
                timestamp TEXT,
                image_path TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                timestamp TEXT,
                camera_id TEXT,
                status TEXT
            )
        """)

        self.connection.commit()

    def close(self):
        self.connection.close()