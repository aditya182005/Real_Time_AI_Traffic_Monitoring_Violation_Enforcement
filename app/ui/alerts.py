import streamlit as st

from app.alerts import twilio_alert
from app.ui import analytics, theme
from app.ui.helpers import show_records

SETTING_LABELS = {
    "TWILIO_ACCOUNT_SID": "Account SID",
    "TWILIO_AUTH_TOKEN": "Auth token",
    "TWILIO_PHONE_NUMBER": "Twilio phone number",
    "ALERT_TO_PHONE": "Phone to alert",
}

TEST_MESSAGE = twilio_alert.TEST_MESSAGE


def _twilio_panel():
    status = twilio_alert.config_status()

    tags = "".join(
        theme.pill(
            f"{label}: {'set' if status[name] else 'missing'}",
            "ok" if status[name] else "danger",
        )
        for name, label in SETTING_LABELS.items()
    )
    tags += theme.pill(
        "Voice call on" if twilio_alert.voice_call_enabled()
        else "Voice call off",
        "info",
    )

    theme.card(
        "Twilio",
        tags + '<div class="note">Settings are read from the environment or '
               "a <code>.env</code> file (copy <code>.env.example</code>). "
               "Secret values are never shown here.</div>",
    )

    configured = twilio_alert.is_configured()

    for problem in twilio_alert.config_problems():
        st.warning(problem)

    ready = twilio_alert.is_ready()

    if st.button("Send a test message", disabled=not ready,
                 key="twilio_test",
                 help="Sends one SMS to the number in ALERT_TO_PHONE."):
        with st.spinner("Sending…"):
            result = twilio_alert.send_alert(TEST_MESSAGE)

        if result.startswith("sent"):
            st.success(f"Test message result: {result}.")
        else:
            st.error(f"Test message result: {result}.")

    if not configured:
        st.caption("Fill in the four settings above to turn this on.")
    else:
        st.caption(
            "To check your setup from a terminal: "
            "`python -m app.alerts.twilio_alert --send`"
        )


def render(data):
    collisions = data["collisions"]
    priority = data["priority"]

    theme.page_head(
        "Alerts",
        "Collision alerts sent through Twilio, and emergency vehicles that "
        "were given priority.",
    )

    counts = analytics.alert_status_counts(collisions)
    metrics = analytics.alert_metrics(collisions)
    theme.gantry([
        ("Alerts sent", counts["sent"], "SMS accepted by Twilio",
         "green" if counts["sent"] else "white"),
        ("Pending", counts["pending"], "still sending", "white"),
        ("Skipped", counts["skipped"], "not set up, or alerts off", "amber"),
        ("Failed", counts["failed"], "Twilio reported an error",
         "red" if counts["failed"] else "white"),
        ("Success rate",
         "–" if metrics["success_rate"] is None
         else f"{metrics['success_rate'] * 100:.0f}%",
         f"of {metrics['attempted']} attempted" if metrics["attempted"]
         else "no alerts attempted yet", "white"),
        ("Typical delay",
         "–" if metrics["median_ms"] is None
         else f"{metrics['median_ms'] / 1000:.1f} s",
         "detection to Twilio's reply (median)"
         if metrics["median_ms"] is not None
         else "no sent alerts yet", "white"),
    ])

    _twilio_panel()

    st.subheader("Collision alerts")
    show_records(collisions, "Possible collisions", "collision_alerts.csv",
                 "dl_alert_collisions")
    st.warning(
        "A collision alert comes from a heuristic. A person must verify "
        "it before anyone is sent."
    )

    st.subheader("Emergency priority")
    show_records(priority, "Priority requests", "priority_requests.csv",
                 "dl_alert_priority")
    st.info(
        "When an emergency vehicle is confirmed in view, the simulated "
        "signal turns green for a short time. No real signal is controlled."
    )
