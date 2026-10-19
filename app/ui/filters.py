"""The date filter bar shown above the data pages.

It lives on the page, not in the sidebar, so the sidebar is only navigation.
"""

from datetime import date, timedelta

import streamlit as st

PRESETS = ("Last 7 days", "Last 30 days", "Last 90 days", "All time",
           "Custom")
DEFAULT_PRESET = "Last 30 days"
EARLIEST = date(2000, 1, 1)


def preset_range(name, today=None):
    """``(start, end)`` for a preset; ``None`` for Custom."""

    today = today or date.today()

    days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}

    if name in days:
        return today - timedelta(days=days[name]), today

    if name == "All time":
        return EARLIEST, today

    return None


def date_range_bar():
    """Draw the bar and return ``(start, end)``."""

    today = date.today()

    with st.container(border=True):
        choice = st.radio("Show records from", PRESETS,
                          index=PRESETS.index(DEFAULT_PRESET),
                          horizontal=True, key="range_preset")
        chosen = preset_range(choice, today)

        if chosen is not None:
            return chosen

        left, right = st.columns(2)
        start = left.date_input("From", value=today - timedelta(days=30),
                                key="start_date")
        end = right.date_input("To", value=today, key="end_date")

    return start, end
