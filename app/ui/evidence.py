from pathlib import Path

import pandas as pd
import streamlit as st

from app import challan, paths, review
from app.ui import auth, theme
from app.ui.data import ROOT
from app.ui.helpers import show_image


def resolve_evidence_path(value):
    """Resolve a stored path, but only if it stays inside the project or
    the configured data folder (see app/paths.py).

    Paths come from the database; refusing anything else means a tampered
    record cannot make the page read other files.
    """

    if value is None or pd.isna(value) or not str(value).strip():
        return None

    path = Path(str(value))

    if not path.is_absolute():
        path = ROOT / path

    path = path.resolve()

    if not any(path.is_relative_to(root.resolve())
               for root in paths.ALLOWED_EVIDENCE_ROOTS):
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

    evidence["review"] = [
        review.status_of(row.get("review_status"))
        if row["kind"] == "Violation" else ""
        for _, row in evidence.iterrows()
    ]

    choice = st.radio(
        "Show", ["All", "Pending review", "Approved", "Rejected"],
        horizontal=True, key="evidence_review_filter")
    wanted = {"Pending review": review.PENDING, "Approved": review.APPROVED,
              "Rejected": review.REJECTED}.get(choice)

    if wanted:
        evidence = evidence[evidence["review"] == wanted].reset_index(drop=True)

        if evidence.empty:
            st.info(f"No violations are {choice.lower()}.")
            return

    def describe(i):
        row = evidence.iloc[i]
        plate = row.get("plate_text")
        plate = f", plate {plate}" if isinstance(plate, str) and plate else ""
        state = f" [{row['review']}]" if row.get("review") else ""

        return (
            f"{row['kind']}, {row.get('violation_type', '')}, "
            f"track {row.get('track_id', row.get('track_id_1', '?'))}"
            f"{plate}, {str(row.get('timestamp', ''))[:19]}{state}"
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

        _review_controls(row)

        st.markdown("**Details**")
        st.json({
            key: (None if pd.isna(value) else str(value))
            for key, value in row.items()
            if key not in ("evidence_path", "crop_path")
        })


def _review_controls(row):
    """Approve / reject a violation (operators and admins)."""

    if row.get("kind") != "Violation" or pd.isna(row.get("id")):
        return

    record_id = int(row["id"])
    status = review.status_of(row.get("review_status"))
    st.markdown("**Review**")
    st.markdown(theme.pill(
        status, {"approved": "ok", "rejected": "danger"}.get(status, "warn")),
        unsafe_allow_html=True)

    by = row.get("reviewed_by")

    if isinstance(by, str) and by:
        st.caption(f"By {by}, {str(row.get('reviewed_at', ''))[:19]} UTC")

    if status == review.APPROVED:
        _challan_button(record_id)

    if not auth.can("operate"):
        st.caption("Operators and admins can approve or reject.")
        return

    note = st.text_input("Note (optional)", key=f"review_note_{record_id}")
    approve, reject = st.columns(2)
    decision = None

    if approve.button("Approve", key=f"approve_{record_id}"):
        decision = review.APPROVED
    elif reject.button("Reject", key=f"reject_{record_id}"):
        decision = review.REJECTED

    if decision:
        user = auth.current_user() or {}

        try:
            review.set_status(
                record_id, decision, user.get("name") or "unknown",
                role=auth.current_role(), note=note,
                address=auth.client_address())
        except review.ReviewError as exc:
            st.error(str(exc))
            return

        st.cache_data.clear()
        st.rerun()


def _challan_button(record_id):
    """Download the e-challan PDF for an approved violation."""

    try:
        record = challan.fetch_record(record_id)
        data = challan.build_pdf(record)
        name = challan.challan_number(record) + ".pdf"
    except (challan.ChallanError, OSError) as exc:
        st.caption(f"E-challan unavailable: {exc}")
        return

    st.download_button("Download e-challan (PDF)", data=data,
                       file_name=name, mime="application/pdf",
                       key=f"challan_{record_id}")
