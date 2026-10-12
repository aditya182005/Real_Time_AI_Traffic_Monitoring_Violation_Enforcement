"""A password gate for the dashboard.

Set ``DASHBOARD_PASSWORD`` to require a password before any page is shown.
Without it the app is open, which is fine on your own computer. Set
``APP_ENV=production`` (the Docker image does) and the app refuses to run
without a password, so a public server is never left open by accident.

This is one shared password, not user accounts. For several users with
their own logins, put the app behind an identity-aware proxy (see DEPLOY.md).
"""

import hmac
import os
import time

import streamlit as st

from app.ui import theme

# After this many wrong guesses in one session, each further guess is slowed.
FREE_ATTEMPTS = 3
MAX_DELAY_SECONDS = 10


def configured_password():
    return os.getenv("DASHBOARD_PASSWORD") or None


def is_production():
    return os.getenv("APP_ENV", "").strip().lower() in ("production", "prod")


def password_matches(entered, expected):
    """Compare in constant time so timing does not reveal the password."""

    return hmac.compare_digest(
        str(entered).encode("utf-8"), str(expected).encode("utf-8")
    )


def _delay_for(failures):
    if failures < FREE_ATTEMPTS:
        return 0

    return min(2 ** (failures - FREE_ATTEMPTS + 1), MAX_DELAY_SECONDS)


def require_login():
    """Call before drawing anything. Stops the page unless signed in."""

    password = configured_password()

    if password is None:
        if is_production():
            st.error(
                "This server is running in production mode but "
                "DASHBOARD_PASSWORD is not set, so it will not show any "
                "data. Set DASHBOARD_PASSWORD and restart."
            )
            st.stop()

        return

    if st.session_state.get("authenticated"):
        return

    theme.page_head("Sign in", "Enter the dashboard password to continue.")

    with st.form("login"):
        entered = st.text_input("Password", type="password",
                                key="login_password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        failures = st.session_state.get("login_failures", 0)
        pause = _delay_for(failures)

        if pause:
            time.sleep(pause)

        if password_matches(entered, password):
            st.session_state["authenticated"] = True
            st.session_state["login_failures"] = 0
            st.rerun()
        else:
            st.session_state["login_failures"] = failures + 1
            st.error("That password is not correct.")

    st.stop()


def logout_button():
    """A sign-out button for the sidebar (only when a password is set)."""

    if configured_password() is None:
        return

    if st.button("Sign out", key="logout"):
        st.session_state["authenticated"] = False
        st.rerun()
