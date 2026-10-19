import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# `streamlit run app/main.py` puts app/ on sys.path, not the project root.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.ui import about, admin, alerts, analytics, dashboard  # noqa: E402
from app.ui import auth, evidence, filters, live_page, theme, upload  # noqa: E402
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

    uploads = paths.OUTPUT_DIR / "uploads"
    housekeeping.cleanup_staging(uploads)

    return housekeeping.cleanup_old_runs(
        uploads, housekeeping.retention_days()
    )


try:
    _housekeeping()
except OSError:
    pass  # cleaning up is best effort; never block the app on it

# Pages grouped by what the person is doing, in the order they are listed.
NAV = (
    ("Overview", {"Dashboard": "dashboard"}),
    ("Monitor", {"Analyze footage": "upload", "Live camera": "live"}),
    ("Review", {"Evidence": "evidence", "Alerts": "alerts"}),
    ("System", {"About": "about", "Admin": "admin"}),
)

PAGES = {}
GROUP_STARTS = {}     # position in PAGES -> group heading

for heading, members in NAV:
    first = True

    for label, key in members.items():
        if key == "admin" and not auth.can("admin"):
            continue

        if first:
            GROUP_STARTS[len(PAGES)] = heading
            first = False

        PAGES[label] = key

# Pages that read the database and so need a date range.
DATA_PAGES = ("dashboard", "evidence", "alerts")

with st.sidebar:
    theme.brand()
    st.caption("Smart traffic monitoring")

    theme.nav_groups(GROUP_STARTS)

    # First visit with nothing recorded yet: start where the data comes from.
    labels = list(PAGES)
    first_page = 0 if DB_PATH.exists() else labels.index("Analyze footage")

    choice = st.radio("Go to", labels, index=first_page,
                      label_visibility="collapsed")
    page = PAGES[choice]

    auth.logout_button()

    st.divider()
    st.caption(
        f"Database: `{DB_PATH.name}` "
        f"({'found' if DB_PATH.exists() else 'not created yet'})"
    )

start_date = end_date = None

if page in DATA_PAGES:
    start_date, end_date = filters.date_range_bar()

    if start_date > end_date:
        st.error("The start date is after the end date.")
        st.stop()

if page == "upload":
    upload.render()
elif page == "live":
    live_page.render()
elif page == "admin":
    admin.render()
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
