
import sqlite3
from pathlib import Path
from datetime import date

import pandas as pd
import streamlit as st


# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "traffic_agent.db"

st.set_page_config(
    page_title="Traffic Agent Dashboard",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------
# 2. DATABASE FUNCTIONS
# --------------------------------------------------

TABLES = {
    "Unified Violations": "violation_records",
    "Red-Light Violations (Legacy)": "violations",
    "Speeding Violations (Legacy)": "speed_violations",
    "Emergency Priority Events": "priority_events",
    "Collision Events": "collision_events",
}


@st.cache_data(ttl=10)
def load_table(table_name):
    """Load a database table. Return an empty DataFrame if unavailable."""

    allowed_tables = set(TABLES.values())

    if table_name not in allowed_tables:
        return pd.DataFrame()

    if not DB_PATH.exists():
        return pd.DataFrame()

    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            existing_tables = pd.read_sql_query(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """,
                conn,
            )["name"].tolist()

            if table_name not in existing_tables:
                return pd.DataFrame()

            return pd.read_sql_query(
                f'SELECT * FROM "{table_name}"',
                conn,
            )

    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame()


def filter_by_date(df, start_date, end_date):
    """Filter records by timestamp, including the complete end date."""

    if df.empty or "timestamp" not in df.columns:
        return df.copy()

    result = df.copy()

    timestamps = pd.to_datetime(
        result["timestamp"],
        errors="coerce",
        utc=True,
    )

    start = pd.Timestamp(start_date, tz="UTC")
    end = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)

    return result.loc[
        timestamps.ge(start) & timestamps.lt(end)
    ].copy()


def export_csv(df):
    """Convert a DataFrame to downloadable CSV bytes."""

    return df.to_csv(index=False).encode("utf-8-sig")


def resolve_evidence_path(value):
    """Resolve evidence paths stored as absolute or project-relative paths."""

    if pd.isna(value) or not str(value).strip():
        return None

    path = Path(str(value))

    if not path.is_absolute():
        path = ROOT / path

    return path.resolve()


def show_records(df, title, download_name):
    """Display records and provide a CSV download."""

    st.subheader(title)

    if df.empty:
        st.info("No records found for the selected date range.")
        return

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        label=f"Download {title} as CSV",
        data=export_csv(df),
        file_name=download_name,
        mime="text/csv",
        key=f"download_{download_name}",
    )


def count_records(df):
    return len(df) if df is not None else 0


# --------------------------------------------------
# 3. SIDEBAR AND DATE FILTERS
# --------------------------------------------------

st.sidebar.title("🚦 Traffic Agent")
st.sidebar.caption("AI-Based Smart Traffic Monitoring")

if st.sidebar.button("🔄 Refresh Dashboard", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.header("Date Filters")

start_date = st.sidebar.date_input(
    "Start date",
    value=date.today().replace(day=1),
    key="start_date",
)

end_date = st.sidebar.date_input(
    "End date",
    value=date.today(),
    key="end_date",
)

if start_date > end_date:
    st.sidebar.error("Start date cannot be after end date.")
    st.stop()

st.sidebar.caption(f"Database: {DB_PATH.name}")


# --------------------------------------------------
# 4. LOAD DATABASE TABLES
# --------------------------------------------------

raw_data = {
    label: load_table(table_name)
    for label, table_name in TABLES.items()
}

data = {
    label: filter_by_date(df, start_date, end_date)
    for label, df in raw_data.items()
}

unified_df = data["Unified Violations"]
red_light_df = data["Red-Light Violations (Legacy)"]
speed_df = data["Speeding Violations (Legacy)"]
priority_df = data["Emergency Priority Events"]
collision_df = data["Collision Events"]


# --------------------------------------------------
# 5. DASHBOARD HEADER
# --------------------------------------------------

st.title("🚦 Traffic Agent")
st.markdown(
    "AI-Based Smart Traffic Monitoring and "
    "Automated Traffic Violation Monitoring Dashboard"
)

st.caption(
    f"Showing records from {start_date.strftime('%d %b %Y')} "
    f"to {end_date.strftime('%d %b %Y')}"
)

if not DB_PATH.exists():
    st.warning(
        f"Database not found at `{DB_PATH}`. "
        "Run your detection scripts first or check the database path."
    )


# --------------------------------------------------
# 6. OVERVIEW METRICS
# --------------------------------------------------

st.header("Dashboard Overview")

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Unified Violations",
    count_records(unified_df),
)

col2.metric(
    "Legacy Red-Light Events",
    count_records(red_light_df),
)

col3.metric(
    "Legacy Speeding Events",
    count_records(speed_df),
)

col4.metric(
    "Possible Collisions",
    count_records(collision_df),
)

# Fine totals use only the unified table to avoid
# counting legacy records twice.

fine_total = 0

if not unified_df.empty and "fine_amount" in unified_df.columns:
    fine_total = pd.to_numeric(
        unified_df["fine_amount"],
        errors="coerce",
    ).fillna(0).sum()

st.metric("Recorded Demo Fines", f"₹{fine_total:,.0f}")

st.caption(
    "Demo fine totals include only unified violation records. "
    "They are not official legal fines."
)


# --------------------------------------------------
# 7. VIOLATION CHART
# --------------------------------------------------

st.divider()
st.header("Violation Analytics")

if not unified_df.empty and "violation_type" in unified_df.columns:
    chart_data = unified_df.copy()

    chart_data["violation_type"] = (
        chart_data["violation_type"]
        .fillna("Unknown")
        .astype(str)
    )

    counts = (
        chart_data["violation_type"]
        .value_counts()
        .rename_axis("Violation Type")
        .reset_index(name="Count")
    )

    if not counts.empty:
        st.bar_chart(
            counts.set_index("Violation Type")["Count"]
        )
    else:
        st.info("No violation data available for the chart.")

else:
    st.info(
        "The unified violation table is empty or does not contain "
        "a violation_type column."
    )


# --------------------------------------------------
# 8. VIOLATION TYPE FILTER
# --------------------------------------------------

st.divider()
st.header("Filtered Violation Records")

if not unified_df.empty and "violation_type" in unified_df.columns:
    violation_types = sorted(
        unified_df["violation_type"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    selected_types = st.multiselect(
        "Filter by violation type",
        options=violation_types,
        default=violation_types,
    )

    filtered_violations = unified_df[
        unified_df["violation_type"]
        .fillna("Unknown")
        .astype(str)
        .isin(selected_types)
    ].copy()

    show_records(
        filtered_violations,
        "Unified Violation Records",
        "traffic_violations.csv",
    )

else:
    filtered_violations = unified_df.copy()

    show_records(
        filtered_violations,
        "Unified Violation Records",
        "traffic_violations.csv",
    )


# --------------------------------------------------
# 9. EVENT DETAILS TABS
# --------------------------------------------------

st.divider()
st.header("Event Details")

tab_red, tab_speed, tab_priority, tab_collision, tab_evidence = st.tabs(
    [
        "🚦 Red-Light",
        "🏎️ Speeding",
        "🚑 Emergency Priority",
        "💥 Collisions",
        "📷 Evidence",
    ]
)


with tab_red:
    show_records(
        red_light_df,
        "Red-Light Violation Events (Legacy)",
        "red_light_events.csv",
    )


with tab_speed:
    show_records(
        speed_df,
        "Speeding Events (Legacy)",
        "speeding_events.csv",
    )


with tab_priority:
    show_records(
        priority_df,
        "Emergency Priority Events",
        "emergency_priority_events.csv",
    )

    st.info(
        "Emergency priority is simulated for project demonstration. "
        "Detection confidence alone does not confirm an emergency."
    )


with tab_collision:
    show_records(
        collision_df,
        "Possible Collision Events",
        "collision_events.csv",
    )

    st.warning(
        "Collision alerts are heuristic. Bounding-box overlap does "
        "not by itself prove that a collision occurred."
    )


# --------------------------------------------------
# 10. EVIDENCE VIEWER
# --------------------------------------------------

with tab_evidence:
    st.subheader("Violation and Collision Evidence")

    evidence_sources = []

    # Unified violation evidence
    if (
        not unified_df.empty
        and "evidence_path" in unified_df.columns
    ):
        temp = unified_df.copy()
        temp["source"] = "Unified Violation"
        evidence_sources.append(temp)

    # Legacy red-light evidence
    if (
        not red_light_df.empty
        and "evidence_path" in red_light_df.columns
    ):
        temp = red_light_df.copy()
        temp["source"] = "Red-Light (Legacy)"
        evidence_sources.append(temp)

    # Legacy speeding evidence
    if (
        not speed_df.empty
        and "evidence_path" in speed_df.columns
    ):
        temp = speed_df.copy()
        temp["source"] = "Speeding (Legacy)"
        evidence_sources.append(temp)

    # Collision evidence
    if (
        not collision_df.empty
        and "evidence_path" in collision_df.columns
    ):
        temp = collision_df.copy()
        temp["source"] = "Possible Collision"
        evidence_sources.append(temp)

    if not evidence_sources:
        st.info("No evidence records are available.")
    else:
        evidence_df = pd.concat(
            evidence_sources,
            ignore_index=True,
            sort=False,
        )

        evidence_df = evidence_df.dropna(
            subset=["evidence_path"]
        )

        if evidence_df.empty:
            st.info(
                "Records exist, but none contains an evidence path."
            )
        else:
            evidence_df = evidence_df.reset_index(drop=True)

            evidence_df["display_path"] = evidence_df[
                "evidence_path"
            ].astype(str)

            options = list(range(len(evidence_df)))

            selected_index = st.selectbox(
                "Select an evidence record",
                options=options,
                format_func=lambda i: (
                    f"{evidence_df.iloc[i].get('source', 'Event')} | "
                    f"{evidence_df.iloc[i].get('timestamp', 'No timestamp')} | "
                    f"{evidence_df.iloc[i]['display_path']}"
                ),
            )

            selected_record = evidence_df.iloc[selected_index]
            image_path = resolve_evidence_path(
                selected_record["evidence_path"]
            )

            st.write("**Event details**")
            st.json(
                {
                    key: (
                        None if pd.isna(value) else str(value)
                    )
                    for key, value in selected_record.items()
                    if key not in ("display_path",)
                }
            )

            if image_path and image_path.is_file():
                try:
                    st.image(
                        str(image_path),
                        caption=str(image_path.name),
                        use_container_width=True,
                    )
                except Exception as exc:
                    st.error(f"Unable to display evidence: {exc}")
            else:
                st.warning(
                    "Evidence image not found. Check the saved path: "
                    f"{selected_record['evidence_path']}"
                )


# --------------------------------------------------
# 11. DATABASE STATUS
# --------------------------------------------------

st.divider()
with st.expander("Database Status and Record Counts"):
    st.write(f"**Database path:** `{DB_PATH}`")
    st.write(f"**Database exists:** {'Yes' if DB_PATH.exists() else 'No'}")

    status_rows = []

    for label, table_name in TABLES.items():
        df = raw_data[label]

        status_rows.append(
            {
                "Section": label,
                "SQLite Table": table_name,
                "Table Available": not df.empty,
                "Records in Date Range": len(data[label]),
                "Total Records": len(df),
            }
        )

    st.dataframe(
        pd.DataFrame(status_rows),
        use_container_width=True,
        hide_index=True,
    )


# --------------------------------------------------
# 12. FOOTER
# --------------------------------------------------

st.divider()
st.caption(
    "Traffic Agent | Academic Project Prototype | "
    "Detection and alerts require validation before real-world use."
)
