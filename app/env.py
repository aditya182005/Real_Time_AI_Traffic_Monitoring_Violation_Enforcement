"""Small environment checks shared by the app, free of any UI imports."""

import os


def is_production():
    """True when ``APP_ENV`` is ``production`` or ``prod``."""

    return os.getenv("APP_ENV", "").strip().lower() in ("production", "prod")
