from pathlib import Path

import pandas as pd
import streamlit as st

from app.ui import theme
from app.ui.data import ROOT
from app.ui.helpers import show_image


def resolve_evidence_path(value):
    """Resolve a stored path, but only if it stays inside the project.

    Paths come from the database; refusing anything outside the project
    folder means a tampered record cannot make the page read other files.
    """

    if value is None or pd.isna(value) or not str(value).strip():
        return None

    path = Path(str(value))

    if not path.is_absolute():
        path = ROOT / path

    path = path.resolve()

    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        return None

    return path if path.is_file() else None


def _collect(data):
    frames = []

    for key, label in (("violations", "Violation"),
                       ("collisions", "Possible collision"),
                       ("legacy_speed", "Speeding (legacy)")):
        df = data[key]

        if not df.empty and "evidence_path" in df.columns:
            part = df.copy()
            part["kind"] = label
            frames.append(part)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.dropna(subset=["evidence_path"])

    if "timestamp" in combined.columns:
        combined = combined.sort_values("timestamp", ascending=False)

    return combined.reset_index(drop=True)


def render(data):
    theme.page_head(
        "Evidence",
        "The annotated frame and a cropped photo saved with each event.",
    )

    evidence = _collect(data)

    if evidence.empty:
        st.info("No evidence yet. Analyze a video on the “Analyze footage” "
                "page, or run a detection script.")
        return

    def describe(i):
        row = evidence.iloc[i]
        return (
            f"{row['kind']}, {row.get('violation_type', '')}, "
            f"track {row.get('track_id', row.get('track_id_1', '?'))}, "
            f"{str(row.get('timestamp', ''))[:19]}"
        )

    index = st.selectbox(
        "Select an event", options=list(range(len(evidence))),
        format_func=describe,
    )

    row = evidence.iloc[index]
    full = resolve_evidence_path(row["evidence_path"])
    crop = resolve_evidence_path(row["crop_path"]) if "crop_path" in row else None

    left, right = st.columns([2, 1])

    with left:
        st.markdown("**Full frame**")

        if full:
            show_image(str(full), caption=full.name)
        else:
            st.warning("Evidence image not found (or outside the project).")

    with right:
        st.markdown("**Cropped vehicle**")

        if crop:
            show_image(str(crop), caption=crop.name)
        else:
            st.caption("No crop saved for this event.")

        st.markdown("**Details**")
        st.json({
            key: (None if pd.isna(value) else str(value))
            for key, value in row.items()
            if key not in ("evidence_path", "crop_path")
        })
