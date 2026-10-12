"""SQLite helper for tests.

``with sqlite3.connect(...)`` only commits; it does not close the file. On
Windows an open file cannot be deleted, so temporary-directory cleanup then
fails with WinError 32. This commits and closes.
"""

import sqlite3
from contextlib import contextmanager


@contextmanager
def db_connect(path):
    conn = sqlite3.connect(str(path))

    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
