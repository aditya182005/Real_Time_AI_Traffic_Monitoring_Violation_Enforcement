"""Logging setup and the audit trail (no Streamlit imports).

``configure_logging()`` sends application logs to the console (so
``docker compose logs`` shows them) and to a rotating file in the data
folder. ``record()`` writes who did what to both the log and an
``audit_log`` table, which admins can read on the Admin page.

Never put a password, token or camera address in ``detail``. Text is also
stripped of line breaks, so one user's input cannot forge a log line.
"""

import logging
import logging.handlers
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app import paths

DB_PATH = paths.DB_PATH
LOG_DIR = paths.DATA_DIR / "logs"

log = logging.getLogger("traffic_agent.audit")

DETAIL_LIMIT = 300
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")

_configured = False


def configure_logging(force=False):
    """Idempotent: safe to call on every Streamlit rerun."""

    global _configured

    if _configured and not force:
        return

    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").strip().upper(),
                    logging.INFO)
    root = logging.getLogger("traffic_agent")
    root.setLevel(level)
    root.propagate = False

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            LOG_DIR / "traffic_agent.log", maxBytes=5_000_000,
            backupCount=5, encoding="utf-8")
        rotating.setFormatter(formatter)
        root.addHandler(rotating)
    except OSError:
        root.warning("could not open a log file; logging to the console only")

    _configured = True


def clean(text, limit=DETAIL_LIMIT):
    """One line, no control characters, bounded length."""

    text = _CONTROL.sub(" ", str(text if text is not None else "")).strip()

    return text if len(text) <= limit else text[:limit - 1] + "…"


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            username TEXT,
            role TEXT,
            action TEXT NOT NULL,
            detail TEXT,
            address TEXT
        )
    """)


def record(action, user=None, role=None, detail="", address=None):
    """Log an action. Returns True if it was stored; never raises."""

    user, role = clean(user, 64) or None, clean(role, 20) or None
    detail, address = clean(detail), clean(address, 64) or None
    action = clean(action, 40)

    log.info("audit action=%s user=%s role=%s address=%s detail=%s",
             action, user, role, address, detail)

    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        with closing(sqlite3.connect(str(DB_PATH))) as conn:
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO audit_log (timestamp, username, role, action, "
                "detail, address) VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), user, role, action,
                 detail, address))
            conn.commit()

        return True
    except (OSError, sqlite3.Error):
        log.exception("could not store the audit entry")

        return False


def recent(limit=200):
    """Newest-first list of dicts; empty if there is no log yet."""

    if not DB_PATH.exists():
        return []

    try:
        with closing(sqlite3.connect(str(DB_PATH))) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_table(conn)
            rows = conn.execute(
                "SELECT timestamp, username, role, action, detail, address "
                "FROM audit_log ORDER BY id DESC LIMIT ?",
                (int(limit),)).fetchall()
    except sqlite3.Error:
        return []

    return [dict(row) for row in rows]
