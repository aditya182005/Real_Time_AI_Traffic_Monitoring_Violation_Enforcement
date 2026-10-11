import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "traffic_agent.db"

# Dashboard section -> SQLite table
TABLES = {
    "violations": "violation_records",
    "density": "traffic_density",
    "priority": "priority_events",
    "collisions": "collision_events",
    # Older databases only; no script writes here any more.
    "legacy_speed": "speed_violations",
}


@st.cache_data(ttl=10)
def load_table(table_name):
    """Load a table; an empty DataFrame if the table/database is missing."""

    if table_name not in set(TABLES.values()) or not DB_PATH.exists():
        return pd.DataFrame()

    try:
        with closing(sqlite3.connect(str(DB_PATH))) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()

            if not exists:
                return pd.DataFrame()

            return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)

    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


def load_all():
    return {key: load_table(table) for key, table in TABLES.items()}
