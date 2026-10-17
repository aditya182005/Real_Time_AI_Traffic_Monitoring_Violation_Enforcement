"""Tidying up files that uploads leave behind."""

import os
import re
import shutil
import time
from pathlib import Path

# Each analysis run writes into a folder named by an 8-character hex ID.
# Only folders with exactly that name are ever removed.
RUN_FOLDER = re.compile(r"^[0-9a-f]{8}$")


def retention_days():
    """Days to keep finished runs, from UPLOAD_RETENTION_DAYS.

    0 (the default) keeps everything: run folders hold the evidence images
    the Evidence page shows, so nothing is deleted unless you ask for it.
    """

    try:
        return max(0, int(os.getenv("UPLOAD_RETENTION_DAYS", "0")))
    except ValueError:
        return 0


def cleanup_old_runs(upload_root, max_age_days, now=None):
    """Delete run folders older than ``max_age_days``. Returns their names.

    Database records stay; the Evidence page then reports the image as
    missing. The staging folder, symlinks and anything not named like a run
    folder are left alone.
    """

    upload_root = Path(upload_root)

    if max_age_days <= 0 or not upload_root.is_dir():
        return []

    cutoff = (time.time() if now is None else now) - max_age_days * 86400
    removed = []

    for child in upload_root.iterdir():
        if (
            child.is_dir()
            and not child.is_symlink()
            and RUN_FOLDER.match(child.name)
            and child.stat().st_mtime < cutoff
        ):
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)

    return sorted(removed)


STAGING_FOLDER = re.compile(r"^[0-9a-f]{12}$")


def cleanup_staging(upload_root, max_age_hours=24, now=None):
    """Delete staged uploads nobody has touched for ``max_age_hours``.

    Each browser session stages its video in ``_staging/<12 hex>``. Unlike
    run folders these hold no evidence, so they are always cleaned up.
    Returns the removed names.
    """

    staging = Path(upload_root) / "_staging"

    if not staging.is_dir():
        return []

    cutoff = (time.time() if now is None else now) - max_age_hours * 3600
    removed = []

    for child in staging.iterdir():
        if (
            child.is_dir()
            and not child.is_symlink()
            and STAGING_FOLDER.match(child.name)
            and child.stat().st_mtime < cutoff
        ):
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)

    return sorted(removed)
