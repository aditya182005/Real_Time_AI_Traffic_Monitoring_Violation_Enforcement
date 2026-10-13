"""Admin page: system status and the audit log (admins only)."""

import pandas as pd
import streamlit as st

from app import audit, health, live, users
from app.ui import auth, theme
from app.ui.helpers import show_df

LAMPS = {"ok": "ok", "warn": "warn", "fail": "danger"}


def render():
    theme.page_head("Admin", "System status, audit log and accounts.")

    if not auth.require("admin", "open the Admin page"):
        return

    tab_status, tab_audit, tab_users = st.tabs(
        ["System status", "Audit log", "Accounts"])

    with tab_status:
        report = health.run_checks()
        st.markdown(
            theme.pill(f"Overall: {report['status']}",
                       LAMPS[report["status"]]),
            unsafe_allow_html=True)

        for check in report["checks"]:
            st.markdown(
                theme.pill(check["status"], LAMPS[check["status"]])
                + f" **{check['name']}**: {check['detail']}",
                unsafe_allow_html=True)

        snapshots = live.REGISTRY.snapshots()

        if snapshots:
            st.markdown("**Cameras**")
            show_df(pd.DataFrame(snapshots).drop(columns=["recent"]))

        st.caption("From a terminal: `python -m app.health`. "
                   "The container health check uses `/_stcore/health`.")

    with tab_audit:
        rows = audit.recent(300)

        if not rows:
            st.info("Nothing has been recorded yet.")
        else:
            show_df(pd.DataFrame(rows))
            st.caption("Newest first. Passwords and camera passwords are "
                       "never written here.")

    with tab_users:
        try:
            accounts = users.load_users()
        except users.UserError as exc:
            st.error(str(exc))
            return

        if not accounts:
            st.info(
                "No accounts. The app is using "
                f"**{auth.mode()}** sign-in. Create accounts with "
                "`python -m app.users add NAME --role admin`.")
        else:
            show_df(pd.DataFrame(
                [{"user": n, "role": a["role"]}
                 for n, a in sorted(accounts.items())]))

        st.caption("Accounts are managed from the command line so that "
                   "passwords are never typed into a web page: "
                   "`python -m app.users add|passwd|remove|list`.")
