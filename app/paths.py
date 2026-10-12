"""Where the app keeps its files.

By default everything lives in the project folder, as before. Set
``TRAFFIC_AGENT_DATA_DIR`` to keep the database and all generated files
(uploads, evidence, annotated videos) somewhere else, for example a Docker
volume mounted at ``/data``, so they survive the container being replaced.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _data_dir():
    configured = os.getenv("TRAFFIC_AGENT_DATA_DIR", "").strip()

    if not configured:
        return ROOT

    return Path(configured).expanduser().resolve()


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "traffic_agent.db"
OUTPUT_DIR = DATA_DIR / "outputs"

# Evidence images are only ever read from these folders. The dashboard takes
# file paths from the database, so anything outside is refused.
ALLOWED_EVIDENCE_ROOTS = tuple(dict.fromkeys((ROOT, DATA_DIR)))
