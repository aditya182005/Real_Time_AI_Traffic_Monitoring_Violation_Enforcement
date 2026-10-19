import html
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from app.alerts import twilio_alert
from app.ui import analytics, theme
from app.ui.helpers import show_df, show_records

PRIORITY_ACTIVE_MINUTES = 10


def _signal_card(priority_df):
    latest = analytics.latest_row(priority_df)

    if latest is None:
        theme.card(
            "Emergency priority",
            theme.pill("Normal", "ok")
            + '<div class="note">No emergency vehicle has requested '
              "priority in this period.</div>",
        )
        return

    when = pd.to_datetime(latest["timestamp"], utc=True)
    recent = datetime.now(timezone.utc) - when.to_pydatetime() < timedelta(
        minutes=PRIORITY_ACTIVE_MINUTES
    )

    detail = (
        f'<div class="note">Last request: '
        f'{html.escape(str(latest.get("vehicle_class", "emergency vehicle")))}'
        f', confidence {float(latest.get("confidence", 0)):.2f}, '
        f'{when.strftime("%d %b %Y %H:%M UTC")}</div>'
    )

    theme.card(
        "Emergency priority",
        (
            theme.pill("Signal held green", "warn")
            if recent
            else theme.pill("Normal", "ok")
        )
        + detail
        + '<div class="note">Signal control is simulated.</div>',
    )


def _alert_card(collision_df):
    counts = analytics.alert_status_counts(collision_df)

    pills = (
        theme.pill(f"{counts['sent']} sent", "ok")
        + theme.pill(f"{counts['pending']} pending", "info")
        + theme.pill(f"{counts['skipped']} skipped", "warn")
        + theme.pill(f"{counts['failed']} failed", "danger")
    )

    theme.card(
        "Collision alerts",
        pills + '<div class="note">Skipped means Twilio is not set up, or '
                "alerts were off for that run. Details are on the Alerts "
                "page.</div>",
    )


def _overview(data):
    violations = data["violations"]
    collisions = data["collisions"]
    metrics = analytics.alert_metrics(collisions)

    rate = metrics["success_rate"]

    theme.gantry([
        ("Violations", len(violations), "red light, speeding, wrong way",
         "red" if len(violations) else "white"),
        ("Possible collisions", len(collisions), "verify each one",
         "amber" if len(collisions) else "white"),
        ("Alerts delivered", "–" if rate is None else f"{rate * 100:.0f}%",
         f"of {metrics['attempted']} attempted" if metrics["attempted"]
         else "none attempted yet",
         "green" if rate else "white"),
        ("Demo fines", f"₹{analytics.total_fines(violations):,.0f}",
         "not legal fines", "white"),
    ])

    theme.attention(analytics.attention_items(
        data, twilio_alert.is_configured()))

    left, right = st.columns(2)

    with left:
        st.caption("Violations per hour of day (UTC)")

        if violations.empty:
            st.info("No violations in this period.")
        else:
            st.bar_chart(
                analytics.violations_per_hour(violations)
                .set_index("Hour (UTC)")["Violations"]
            )

    with right:
        st.caption("Violations by type")

        if violations.empty:
            st.info("Nothing to compare yet.")
        else:
            st.bar_chart(
                analytics.violations_by_type(violations)
                .set_index("Violation type")
            )

    st.subheader("Latest activity")
    recent = analytics.recent_events(data, limit=10)

    if recent.empty:
        st.info("No events in this period yet.")
    else:
        show_df(recent)


def _violations_tab(data):
    violations = data["violations"]
    legacy_speed = data["legacy_speed"]

    red_light = analytics.by_type(violations, "red_light")
    speeding = analytics.by_type(violations, "speeding")
    wrong_way = analytics.by_type(violations, "wrong_way")

    a, b, c = st.columns(3)
    a.metric("Red light", len(red_light))
    b.metric("Speeding", len(speeding))
    c.metric("Wrong way", len(wrong_way))

    filtered = violations

    if not violations.empty and "violation_type" in violations.columns:
        types = sorted(violations["violation_type"].dropna().unique())
        chosen = st.multiselect(
            "Violation type", options=types, default=types,
            key="filter_types",
        )
        filtered = violations[violations["violation_type"].isin(chosen)]

        if "source" in filtered.columns and filtered["source"].notna().any():
            sources = sorted(filtered["source"].dropna().unique())
            chosen_sources = st.multiselect(
                "Camera or uploaded file", options=sources,
                default=sources, key="filter_sources",
            )
            filtered = filtered[
                filtered["source"].isna()
                | filtered["source"].isin(chosen_sources)
            ]

    show_records(filtered, "Violation records", "violations.csv",
                 "dl_violations")

    if not legacy_speed.empty:
        with st.expander("Older speeding records (legacy table)"):
            show_records(legacy_speed, "Legacy speeding records",
                         "speeding_legacy.csv", "dl_speed_legacy")


def _traffic_tab(data):
    density = data["density"]

    if density.empty:
        st.info(
            "No traffic density data yet. Analyze a video on the "
            "“Analyze footage” page to create some."
        )
        return

    busiest = analytics.peak_hour(density)

    a, b = st.columns(2)
    a.metric("Busiest hour (UTC)",
             "–" if busiest is None else f"{busiest[0]:02d}:00")
    b.metric("Average vehicles then",
             "–" if busiest is None else f"{busiest[1]:.1f}")

    st.caption("Average vehicles in view, by hour of day (UTC)")
    st.line_chart(
        analytics.density_by_hour(density)
        .set_index("Hour (UTC)")["Avg vehicles in view"]
    )

    show_records(density, "Density samples", "traffic_density.csv",
                 "dl_density")


def _alerts_tab(data):
    left, right = st.columns(2)

    with left:
        _signal_card(data["priority"])

    with right:
        _alert_card(data["collisions"])

    show_records(data["collisions"], "Possible collision events",
                 "collision_events.csv", "dl_collision")
    st.warning(
        "Collision alerts are heuristic (overlap + abrupt speed drop). "
        "A person must verify each one."
    )

    show_records(data["priority"], "Emergency priority events",
                 "priority_events.csv", "dl_priority")
    st.info(
        "Emergency priority is simulated. A detection alone does not "
        "confirm a real emergency. Twilio settings and the test message "
        "are on the Alerts page."
    )


def render(data, start_date, end_date):
    theme.page_head(
        "Dashboard",
        f"Records from {start_date.strftime('%d %b %Y')} to "
        f"{end_date.strftime('%d %b %Y')}.",
    )

    overview, violations, traffic, alerts = st.tabs([
        "Overview", "Violations", "Traffic", "Alerts and priority",
    ])

    with overview:
        _overview(data)

    with violations:
        _violations_tab(data)

    with traffic:
        _traffic_tab(data)

    with alerts:
        _alerts_tab(data)
