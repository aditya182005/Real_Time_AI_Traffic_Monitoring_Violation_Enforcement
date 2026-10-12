import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# `streamlit run app/main.py` puts app/ on sys.path, not the project root.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.ui import about, alerts, analytics, dashboard, evidence  # noqa: E402
from app.ui import auth, theme, upload  # noqa: E402
from app.ui.data import DB_PATH, load_all  # noqa: E402

st.set_page_config(
    page_title="Traffic Agent",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.inject_css()

# Stops here unless signed in (when DASHBOARD_PASSWORD is set).
auth.require_login()


@st.cache_resource
def _housekeeping():
    """Once per server start: remove old upload runs if retention is set."""

    from app import housekeeping, paths

    return housekeeping.cleanup_old_runs(
        paths.OUTPUT_DIR / "uploads", housekeeping.retention_days()
    )


try:
    _housekeeping()
except OSError:
    pass  # cleaning up is best effort; never block the app on it

PAGES = {
    "Analyze footage": "upload",
    "Dashboard": "dashboard",
    "Evidence": "evidence",
    "Alerts": "alerts",
    "About": "about",
}

# Pages that read the database and so need a date range.
DATA_PAGES = ("dashboard", "evidence", "alerts")

with st.sidebar:
    theme.brand()
    st.caption("Smart traffic monitoring")

    choice = st.radio("Go to", list(PAGES), label_visibility="collapsed")
    page = PAGES[choice]

    start_date = date.today() - timedelta(days=30)
    end_date = date.today()

    if page in DATA_PAGES:
        st.divider()
        st.markdown("**Date range**")
        start_date = st.date_input("From", value=start_date, key="start_date")
        end_date = st.date_input("To", value=end_date, key="end_date")

        if st.button("Refresh data"):
            st.cache_data.clear()
            st.rerun()

    auth.logout_button()

    st.divider()
    st.caption(
        f"Database: `{DB_PATH.name}` "
        f"({'found' if DB_PATH.exists() else 'not created yet'})"
    )

if start_date > end_date:
    st.sidebar.error("The start date is after the end date.")
    st.stop()

if page == "upload":
    upload.render()
elif page == "about":
    about.render()
else:
    raw = load_all()
    data = {
        key: analytics.filter_by_date(df, start_date, end_date)
        for key, df in raw.items()
    }

    if page == "dashboard":
        if not DB_PATH.exists():
            st.info(
                "No database yet. Analyze a video on the “Analyze footage” "
                "page, or run a detection script, to create one."
            )

        dashboard.render(data, start_date, end_date)
    elif page == "evidence":
        evidence.render(data)
    else:
        alerts.render(data)

st.divider()
st.markdown(
    '<p class="fine-print">Academic prototype. Detections and alerts need '
    "a person to verify them before any real-world use.</p>",
    unsafe_allow_html=True,
)
