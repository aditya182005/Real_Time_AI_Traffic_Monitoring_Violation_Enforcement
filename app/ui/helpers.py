"""Thin wrappers that keep the UI working across Streamlit versions.

Newer Streamlit replaced ``use_container_width=True`` with
``width="stretch"`` (and older versions only know the former), so each
helper tries the new form first and falls back.
"""

import streamlit as st


def show_df(df, **kwargs):
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def show_image(image, caption=None, target=None, **kwargs):
    """Show an image; ``target`` may be a column or ``st.empty()`` slot."""

    target = st if target is None else target

    try:
        target.image(image, caption=caption, width="stretch", **kwargs)
    except Exception:
        try:
            target.image(image, caption=caption, use_container_width=True,
                         **kwargs)
        except Exception:
            target.image(image, caption=caption, **kwargs)


def csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8-sig")


def show_records(df, title, file_name, key):
    """A table with a CSV download, or a friendly empty state."""

    st.subheader(title)

    if df.empty:
        st.info("No records for the selected dates yet.")
        return

    show_df(df)

    st.download_button(
        f"⬇️ Download {title} (CSV)",
        data=csv_bytes(df),
        file_name=file_name,
        mime="text/csv",
        key=key,
    )
