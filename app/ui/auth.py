"""Who may use the dashboard, and what they may do.

Four modes, chosen by ``AUTH_MODE`` or, when that is not set, detected:

``users``     individual accounts with roles (``python -m app.users add``).
              Used automatically once a users file has accounts.
``password``  one shared password in ``DASHBOARD_PASSWORD``. Everyone who
              knows it gets the role in ``DASHBOARD_PASSWORD_ROLE``
              (default ``operator``).
``proxy``     an identity-aware proxy (oauth2-proxy, Cloudflare Access...)
              signs people in and passes their email in a header
              (``AUTH_PROXY_HEADER``, default ``X-Forwarded-Email``). Roles
              come from ``AUTH_PROXY_ADMINS`` / ``AUTH_PROXY_OPERATORS``
              (comma-separated emails); everyone else gets
              ``AUTH_PROXY_DEFAULT_ROLE`` (default ``viewer``). Only use this
              when the app can be reached *only* through the proxy,
              otherwise anyone can send the header themselves.
``none``      open. Fine on your own computer; with ``APP_ENV=production``
              the app refuses to show anything.

Roles are viewer < operator < admin (see app/users.py). A damaged users file
stops the app rather than silently opening it.
"""

import hmac
import os

import streamlit as st

from app import audit, env, ratelimit, users
from app.ui import theme

MODES = ("users", "password", "proxy", "none")


class AuthConfigError(RuntimeError):
    """The sign-in settings are unusable; the app must not open."""


def configured_password():
    return os.getenv("DASHBOARD_PASSWORD") or None


def is_production():
    return env.is_production()


def password_matches(entered, expected):
    """Compare in constant time so timing does not reveal the password."""

    return hmac.compare_digest(
        str(entered).encode("utf-8"), str(expected).encode("utf-8")
    )


def _role_setting(name, default):
    value = os.getenv(name, default).strip().lower()

    if value not in users.ROLES:
        raise AuthConfigError(
            f"{name} must be one of {', '.join(users.ROLES)} (got '{value}').")

    return value


def mode():
    """The active mode. Raises ``AuthConfigError`` if the settings are bad."""

    chosen = os.getenv("AUTH_MODE", "").strip().lower()

    if chosen:
        if chosen not in MODES:
            raise AuthConfigError(
                f"AUTH_MODE must be one of {', '.join(MODES)}.")

        return chosen

    try:
        if users.load_users():
            return "users"
    except users.UserError as exc:
        raise AuthConfigError(str(exc)) from exc

    return "password" if configured_password() else "none"


# -- request details -------------------------------------------------------------

def _headers():
    try:
        return st.context.headers
    except Exception:
        return {}


def client_address():
    """The caller's address if a proxy forwarded it, else ``"unknown"``."""

    forwarded = _headers().get("X-Forwarded-For", "") or ""
    first = forwarded.split(",")[0].strip()

    return first or "unknown"


def _emails(setting):
    return {e.strip().lower() for e in os.getenv(setting, "").split(",")
            if e.strip()}


def proxy_identity():
    """``(name, role)`` from the proxy's header, or None if it is missing."""

    header = os.getenv("AUTH_PROXY_HEADER", "X-Forwarded-Email").strip()
    name = (_headers().get(header, "") or "").strip().lower()

    if not name:
        return None

    if name in _emails("AUTH_PROXY_ADMINS"):
        return name, "admin"

    if name in _emails("AUTH_PROXY_OPERATORS"):
        return name, "operator"

    return name, _role_setting("AUTH_PROXY_DEFAULT_ROLE", "viewer")


# -- session ---------------------------------------------------------------------

def current_user():
    return st.session_state.get("user")


def current_role():
    user = current_user()

    return user["role"] if user else None


def can(permission):
    return users.has_permission(current_role(), permission)


def require(permission, what="do this"):
    """True if the signed-in user has ``permission``; otherwise says why."""

    if can(permission):
        return True

    st.warning(
        f"Your account ({current_role() or 'not signed in'}) cannot {what}. "
        "Ask an operator or admin."
    )

    return False


def _sign_in(name, role):
    st.session_state["user"] = {"name": name, "role": role}
    st.session_state["authenticated"] = True
    st.session_state["login_failures"] = 0


def _stop_with(message):
    st.error(message)
    st.stop()


def _login_form(title, subtitle, with_username):
    theme.page_head(title, subtitle)

    with st.form("login"):
        name = (st.text_input("Username", key="login_username")
                if with_username else "")
        entered = st.text_input("Password", type="password",
                                key="login_password")
        submitted = st.form_submit_button("Sign in")

    return submitted, name.strip().lower(), entered


def _attempt(name, address, check, shared=False):
    """Run one sign-in attempt through the limiter.

    ``check()`` returns the role or None. Returns the role on success.
    With the shared password there is no username, so all attempts count
    against one key named ``shared``: guessing is limited even when the
    caller's address is unknown.
    """

    name = "shared" if shared else name

    wait = ratelimit.locked_seconds(name, address)

    if wait:
        audit.record("login_blocked", user=name, address=address,
                     detail=f"locked for another {wait}s")
        st.error(f"Too many failed attempts. Try again in {wait} seconds.")

        return None

    role = check()

    if role is None:
        ratelimit.record_failure(name, address)
        st.session_state["login_failures"] = (
            st.session_state.get("login_failures", 0) + 1)
        audit.record("login_failed", user=name, address=address)
        st.error("That password is not correct." if shared
                 else "The username or password is not correct.")

        return None

    ratelimit.record_success(name, address)
    audit.record("login_ok", user=name, role=role, address=address)

    return role


def require_login():
    """Call before drawing anything. Stops the page unless signed in."""

    audit.configure_logging()

    try:
        chosen = mode()
    except AuthConfigError as exc:
        _stop_with(f"Sign-in is not set up correctly: {exc}")

    if chosen == "none":
        if is_production():
            _stop_with(
                "This server is running in production mode but "
                "DASHBOARD_PASSWORD is not set (and there are no user "
                "accounts), so it will not show any data. Set "
                "DASHBOARD_PASSWORD or create users with "
                "`python -m app.users add NAME --role admin`, then restart."
            )

        _sign_in("local", "admin")
        return

    if chosen == "proxy":
        try:
            identity = proxy_identity()
        except AuthConfigError as exc:
            _stop_with(f"Sign-in is not set up correctly: {exc}")

        if identity is None:
            _stop_with(
                "No signed-in user was passed by the proxy. Open this app "
                "through the proxy address."
            )

        current = current_user()

        if not current or (current["name"], current["role"]) != identity:
            audit.record("login_ok", user=identity[0], role=identity[1],
                         address=client_address(), detail="via proxy")
            _sign_in(*identity)

        return

    if st.session_state.get("authenticated") and current_user():
        return

    address = client_address()

    if chosen == "password":
        submitted, _, entered = _login_form(
            "Sign in", "Enter the dashboard password to continue.", False)

        if submitted:
            try:
                shared_role = _role_setting("DASHBOARD_PASSWORD_ROLE",
                                            "operator")
            except AuthConfigError as exc:
                _stop_with(f"Sign-in is not set up correctly: {exc}")

            role = _attempt(
                "", address,
                lambda: shared_role if password_matches(
                    entered, configured_password()) else None,
                shared=True)

            if role:
                _sign_in("shared", role)
                st.rerun()

        st.stop()

    submitted, name, entered = _login_form(
        "Sign in", "Sign in with your account.", True)

    if submitted:
        role = _attempt(name, address,
                        lambda: users.authenticate(name, entered))

        if role:
            _sign_in(name, role)
            st.rerun()

    st.stop()


def logout_button():
    """Who is signed in, and a sign-out button when sign-out makes sense."""

    try:
        chosen = mode()
    except AuthConfigError:
        return

    if chosen == "none":
        return

    user = current_user()

    if user:
        st.caption(f"Signed in as **{user['name']}** ({user['role']})")

    if chosen == "proxy":
        return  # the proxy owns the session; signing out happens there

    if st.button("Sign out", key="logout"):
        audit.record("logout", user=(user or {}).get("name"),
                     role=(user or {}).get("role"),
                     address=client_address())
        st.session_state["authenticated"] = False
        st.session_state.pop("user", None)
        st.rerun()
