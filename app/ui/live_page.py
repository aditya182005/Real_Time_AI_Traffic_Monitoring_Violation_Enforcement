"""Live camera page: start, watch and stop a camera stream.

The analysis runs in a background thread owned by ``app.live.REGISTRY``, so
it keeps going when the browser tab is closed. This page only controls it
and shows its latest picture and counters.
"""

import streamlit as st

from app import audit, live
from app.analysis import validate_settings
from app.ui import auth, theme, upload
from app.ui.helpers import show_image

REFRESH_SECONDS = 2


def _who():
    user = auth.current_user() or {}

    return {"user": user.get("name"), "role": user.get("role"),
            "address": auth.client_address()}


def _pick_source():
    """``(label, source)`` chosen on the page, or None."""

    cameras = live.configured_cameras()
    custom = live.custom_addresses_allowed()
    other = "Other address or webcam…"
    options = list(cameras) + ([other] if custom else [])

    if not options:
        st.info(
            "No cameras are set up. An administrator can list them in the "
            "`LIVE_CAMERAS` setting, for example "
            "`Gate=rtsp://user:pass@192.168.1.20/stream1`.")
        return None

    choice = st.selectbox("Camera", options, key="live_camera")

    if choice in cameras:
        return choice, cameras[choice]

    if not custom:      # defence in depth: never trust the widget's value
        return None

    typed = st.text_input(
        "Camera address, or a webcam number such as 0", type="password",
        key="live_address",
        help="rtsp://, rtsps://, http://, https:// or rtmp://. Hidden while "
             "you type because addresses often contain a password.")

    try:
        return "CAM-01", live.parse_source(typed)
    except ValueError as exc:
        if typed:
            st.error(str(exc))

        return None


def _start_controls():
    st.subheader("Start monitoring")

    picked = _pick_source()
    default = picked[0] if picked else "CAM-01"

    settings, _, _ = upload._settings_panel(
        run_options=False, default_camera=default,
        camera_key=f"camera_id_{default}")
    problems = validate_settings(settings)

    for problem in problems:
        st.error(problem)

    if picked is None:
        return

    name = settings.camera_id.strip() or "CAM-01"
    source = live.parse_source(picked[1])

    st.caption(
        "The signal is simulated. Stop line and other positions are "
        "percentages of the picture, so check them on a still frame first "
        "(Analyze footage).")

    if not st.button("Start live monitoring", type="primary",
                     key="live_start", disabled=bool(problems)):
        return

    models = upload._load_models(settings.use_emergency)

    if models is None:
        return

    detector, emergency = models
    reader, locator = (upload.load_plate_tools() if settings.read_plates
                       else (None, None))

    from app.tracking.tracker import VehicleTracker

    try:
        monitor = live.REGISTRY.start(
            name, source, settings, detector, VehicleTracker(),
            emergency_detector=emergency, plate_reader=reader,
            plate_locator=locator)
    except live.LiveError as exc:
        st.error(str(exc))
        return

    audit.record("live_start", detail=f"{name} {live.redact(source)}",
                 **_who())
    st.cache_data.clear()
    st.rerun()


def _show_monitor(name, may_stop):
    monitor = live.REGISTRY.get(name)

    if monitor is None:
        return

    snap = monitor.snapshot()
    lamp = {"running": "green", "starting": "amber",
            "failed": "red"}.get(snap["state"], "white")
    connection = snap["connection"]

    theme.gantry([
        (f"{snap['camera']}", snap["state"].capitalize(),
         f"connection: {connection}", lamp),
        ("Analysis speed", f"{snap['analysis_fps']} FPS",
         f"{snap['dropped_frames']} frame(s) skipped to keep up",
         "amber" if snap["dropped_frames"] else "green"),
        ("Violations", snap["violations"], "since it started",
         "red" if snap["violations"] else "white"),
        ("Possible collisions", snap["collisions"], "verify each one",
         "amber" if snap["collisions"] else "white"),
        ("Running for", f"{snap['running_seconds']} s",
         f"{snap['reconnects']} reconnect(s)", "white"),
    ])

    if snap["error"]:
        st.error(f"This camera stopped: {snap['error']}")

    jpeg = monitor.latest_jpeg()

    if jpeg:
        show_image(jpeg, caption="Latest analyzed frame")
    elif snap["state"] in ("starting", "running"):
        st.caption("Waiting for the first picture…")

    if snap["recent"]:
        st.markdown("**Recent events**")
        st.markdown("\n".join(f"- {line}" for line in snap["recent"][:10]))

    if monitor.active and may_stop:
        if st.button("Stop monitoring", key=f"live_stop_{name}"):
            live.REGISTRY.stop(name)
            audit.record("live_stop", detail=name, **_who())
            st.rerun()


def _fragment(function):
    """Refresh the status by itself where this Streamlit supports it."""

    wrapper = getattr(st, "fragment", None)

    return wrapper(run_every=REFRESH_SECONDS)(function) if wrapper \
        else function


@_fragment
def _status_panel():
    names = live.REGISTRY.names()

    if not names:
        st.info("No camera is running.")
        return

    may_stop = auth.can("operate")

    for name in names:
        _show_monitor(name, may_stop)

    if not getattr(st, "fragment", None):
        st.button("Refresh", key="live_refresh")


def render():
    theme.page_head(
        "Live camera",
        "Watch a camera stream and check traffic as it happens. Results go "
        "to the same Dashboard, Evidence and Alerts pages.",
    )

    _status_panel()

    if not auth.can("operate"):
        st.caption("Your account can watch but not start or stop cameras.")
        return

    st.divider()
    _start_controls()
