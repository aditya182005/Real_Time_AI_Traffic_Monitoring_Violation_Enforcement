import sqlite3


class Database:

    def __init__(self, db_name="traffic_agent.db"):
        self.connection = sqlite3.connect(db_name)

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