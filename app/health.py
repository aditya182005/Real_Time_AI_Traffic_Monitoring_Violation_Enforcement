"""Is the system healthy? (no Streamlit imports)

    python -m app.health            # readable report; exit 1 if anything failed
    python -m app.health --json     # for scripts and monitors

The same checks feed the Admin page. Streamlit itself already answers
``/_stcore/health`` (used by the Docker health check); this adds the things
that matter to Traffic Agent: can it write its database, is the disk filling
up, are the cameras running, are alerts failing.
"""

import argparse
import json
import shutil
import sqlite3
import sys
from contextlib import closing

from app import paths
from app.violation import violation_logger

OK, WARN, FAIL = "ok", "warn", "fail"

MIN_FREE_MB = 500


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def check_database():
    path = violation_logger.DB_PATH

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with closing(sqlite3.connect(str(path), timeout=5)) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS _health (x INTEGER)")
            conn.execute("INSERT INTO _health VALUES (1)")
            conn.execute("DELETE FROM _health")
            conn.commit()
    except (OSError, sqlite3.Error) as exc:
        return _check("database", FAIL, f"cannot write {path.name}: {exc}")

    return _check("database", OK, f"{path.name} is writable")


def check_disk():
    try:
        free = shutil.disk_usage(paths.DATA_DIR).free // (1024 * 1024)
    except OSError as exc:
        return _check("disk", FAIL, f"cannot read the data folder: {exc}")

    if free < MIN_FREE_MB:
        return _check("disk", WARN,
                      f"only {free} MB free in the data folder")

    return _check("disk", OK, f"{free} MB free")


def check_alerts():
    """Failed alerts in the database (never the message contents)."""

    path = violation_logger.DB_PATH

    if not path.exists():
        return _check("alerts", OK, "no alerts yet")

    try:
        with closing(sqlite3.connect(str(path))) as conn:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='collision_events'"
            ).fetchone()

            if not has_table:
                return _check("alerts", OK, "no alerts yet")

            columns = {r[1] for r in conn.execute(
                "PRAGMA table_info(collision_events)")}

            if "alert_status" not in columns:
                return _check("alerts", OK, "no alerts yet")

            sent, failed = conn.execute(
                "SELECT SUM(alert_status LIKE 'sent%'), "
                "SUM(alert_status LIKE 'failed%') FROM collision_events"
            ).fetchone()
    except sqlite3.Error as exc:
        return _check("alerts", WARN, f"could not read alerts: {exc}")

    sent, failed = sent or 0, failed or 0

    if failed and failed >= sent:
        return _check("alerts", WARN,
                      f"{failed} alert(s) failed, {sent} sent. See the "
                      "Alerts page.")

    return _check("alerts", OK, f"{sent} sent, {failed} failed")


def check_twilio():
    try:
        from app.alerts import twilio_alert
    except Exception as exc:  # pragma: no cover - defensive
        return _check("twilio", WARN, f"could not be checked ({exc})")

    if not twilio_alert.is_configured():
        return _check("twilio", WARN, "not configured; alerts are skipped")

    problems = twilio_alert.config_problems()

    return _check("twilio", WARN, " ".join(problems)) if problems \
        else _check("twilio", OK, "configured")


def check_cameras(monitors=None):
    if monitors is None:
        from app import live

        monitors = live.REGISTRY.snapshots()

    if not monitors:
        return _check("cameras", OK, "no live cameras running")

    bad = [m for m in monitors if m["state"] == "failed"
           or m["connection"] in ("lost", "reconnecting")]

    if bad:
        names = ", ".join(m["camera"] for m in bad)

        return _check("cameras", WARN, f"needs attention: {names}")

    return _check("cameras", OK, f"{len(monitors)} running")


def run_checks(monitors=None):
    checks = [check_database(), check_disk(), check_alerts(),
              check_twilio(), check_cameras(monitors)]
    status = (FAIL if any(c["status"] == FAIL for c in checks)
              else WARN if any(c["status"] == WARN for c in checks)
              else OK)

    return {"status": status, "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Traffic Agent health check")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_checks()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for check in report["checks"]:
            print(f"[{check['status'].upper():<4}] {check['name']}: "
                  f"{check['detail']}")

        print(f"\nOverall: {report['status']}")

    return 1 if report["status"] == FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
