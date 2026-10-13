import re
import shutil
import uuid
from pathlib import Path

import cv2
import pandas as pd
import streamlit as st

from app import audit, media, paths, plates
from app.alerts import twilio_alert
from app.analysis import (
    VideoSettings,
    analyze_image,
    build_processor,
    pixel_col,
    pixel_row,
    validate_settings,
)
from app.annotate import draw_calibration
from app.detection.emergency_detector import EmergencyDetector
from app.ui import auth, theme
from app.ui.data import ROOT
from app.ui.helpers import csv_bytes, show_df, show_image

UPLOAD_ROOT = paths.OUTPUT_DIR / "uploads"
STAGING_DIR = UPLOAD_ROOT / "_staging"
SAMPLE_VIDEO = ROOT / "data" / "videos" / "traffic.mp4"
MAX_IMAGES = 12

MAX_FRAME_CHOICES = {
    "First 300 frames (quick test)": 300,
    "First 900 frames": 900,
    "First 1,800 frames": 1800,
    "Whole video (slow on a CPU)": None,
}

SIGNAL_MODES = {
    "Always red": "red",
    "Always green": "green",
    "Cycle red and green": "cycle",
}

DIRECTIONS = {
    "Down the image (toward the camera)": "down",
    "Up the image (away from the camera)": "up",
}

VIOLATION_NAMES = {
    "red_light": "Red light",
    "speeding": "Speeding",
    "wrong_way": "Wrong way",
}


# -- model loading (cached across reruns) -----------------------------------

@st.cache_resource(show_spinner="Loading the vehicle detection model…")
def load_vehicle_detector():
    from app.detection.detector import VehicleDetector

    return VehicleDetector()


@st.cache_resource(show_spinner="Loading the emergency-vehicle model…")
def load_emergency_detector():
    return EmergencyDetector()


@st.cache_resource(show_spinner="Loading the plate reader (first time only)…")
def load_plate_tools():
    return plates.load_tools()


def _load_models(use_emergency):
    """Returns ``(vehicle_detector, emergency_detector_or_None)`` or None."""

    try:
        detector = load_vehicle_detector()
        emergency = load_emergency_detector() if use_emergency else None
    except ImportError:
        st.error(
            "The detection libraries are not installed. "
            "Run `pip install -r requirements.txt`, then restart the app."
        )
        return None
    except Exception as exc:
        st.error(f"Could not load the detection model: {exc}")
        return None

    return detector, emergency


def _clean_name(name, limit=60):
    """Display-safe version of a user-supplied file name."""

    name = Path(str(name)).name
    name = re.sub(r"[^\w.\- ]", "_", name)

    return name[:limit] or "upload"


def _download_stem(name):
    return re.sub(r"[^A-Za-z0-9_-]", "_", Path(name).stem)[:40] or "file"


# -- images -----------------------------------------------------------------

def _images_tab():
    st.markdown(
        "Upload one or more photos of a road or junction. The model finds "
        "cars, motorcycles, buses and trucks, and emergency vehicles when "
        "the custom model is installed."
    )

    files = st.file_uploader(
        "Drop traffic images here",
        type=[ext.lstrip(".") for ext in media.ALLOWED_IMAGE_EXTENSIONS],
        accept_multiple_files=True,
        key="image_files",
        help="JPG, PNG, BMP or WebP. Up to 200 MB each.",
    )

    left, right = st.columns(2)
    conf = left.slider("Detection confidence", 0.10, 0.90, 0.35, 0.05,
                       key="image_conf",
                       help="Lower finds more vehicles but adds false hits.")

    emergency_ready = EmergencyDetector.available()
    use_emergency = right.checkbox(
        "Also detect emergency vehicles",
        value=emergency_ready,
        disabled=not emergency_ready,
        key="image_emergency",
        help=None if emergency_ready else
        "Needs models/emergency_vehicle.pt. See the README, section "
        "“Training the emergency-vehicle model”.",
    )

    if files and len(files) > MAX_IMAGES:
        st.warning(f"Only the first {MAX_IMAGES} images will be analyzed.")

    if st.button("Analyze images", type="primary", disabled=not files,
                 key="run_images"):
        models = _load_models(use_emergency)

        if models is not None:
            detector, emergency = models
            results = []
            batch = files[:MAX_IMAGES]
            bar = st.progress(0.0, text="Analyzing…")

            for number, uploaded in enumerate(batch, start=1):
                name = _clean_name(uploaded.name)

                try:
                    image = media.decode_image(uploaded.getvalue())
                    report = analyze_image(image, detector, emergency, conf=conf)

                    results.append({
                        "name": name,
                        "jpg": media.encode_image(report.annotated),
                        "counts": report.counts,
                        "vehicles": len(report.vehicles),
                        "emergencies": report.emergencies,
                        "seconds": report.seconds,
                        "error": None,
                    })
                except ValueError as exc:
                    results.append({"name": name, "error": str(exc)})

                bar.progress(number / len(batch),
                             text=f"Analyzed {number} of {len(batch)}")

            bar.empty()
            st.session_state["image_results"] = results

    results = st.session_state.get("image_results")

    if not results:
        return

    st.divider()
    head, clear = st.columns([5, 1])
    head.subheader("Results")

    if clear.button("Clear results", key="clear_images"):
        st.session_state.pop("image_results", None)
        st.rerun()

    ok = [r for r in results if not r["error"]]

    theme.gantry([
        ("Images analyzed", len(ok),
         f"{len(results) - len(ok)} could not be read",
         "red" if len(results) > len(ok) else "white"),
        ("Vehicles found", sum(r["vehicles"] for r in ok), "across all images",
         "green"),
        ("Emergency vehicles", sum(len(r["emergencies"]) for r in ok),
         "simulated priority requests", "amber"),
        ("Time per image",
         f"{(sum(r['seconds'] for r in ok) / len(ok)):.2f} s" if ok else "–",
         "detection only", "white"),
    ])

    grid = st.columns(2)

    for index, result in enumerate(results):
        with grid[index % 2]:
            with st.container(border=True):
                st.markdown(f"**{result['name']}**")

                if result["error"]:
                    st.error(result["error"])
                    continue

                show_image(result["jpg"])

                pills = "".join(
                    theme.pill(f"{count} {name}", "info")
                    for name, count in sorted(result["counts"].items())
                ) or theme.pill("No vehicles found", "warn")

                if result["emergencies"]:
                    pills += theme.pill("Priority request (simulated)", "warn")

                st.markdown(pills, unsafe_allow_html=True)

                st.download_button(
                    "Download annotated image",
                    data=result["jpg"],
                    file_name=f"annotated_{_download_stem(result['name'])}.jpg",
                    mime="image/jpeg",
                    key=f"dl_img_{index}",
                )

    table = pd.DataFrame([
        {
            "File": r["name"],
            "Vehicles": r["vehicles"],
            "Breakdown": ", ".join(f"{n} {c}" for c, n in
                                   sorted(r["counts"].items())),
            "Emergency vehicles": len(r["emergencies"]),
            "Seconds": round(r["seconds"], 2),
        }
        for r in ok
    ])

    if not table.empty:
        st.markdown("**Summary**")
        show_df(table)
        st.download_button("Download summary (CSV)", data=csv_bytes(table),
                           file_name="image_analysis.csv", mime="text/csv",
                           key="dl_image_summary")


# -- video: staging ---------------------------------------------------------

def _read_properties(path):
    cap = cv2.VideoCapture(str(path))
    ok, first = cap.read() if cap.isOpened() else (False, None)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()

    if not ok:
        return None

    return {
        "path": str(path),
        "first_frame": first,
        "height": first.shape[0],
        "width": first.shape[1],
        "fps": fps,
        "frames": frames,
    }


def _stage_video(uploaded):
    """Save the upload to a fixed, safe location and read its properties."""

    key = f"{uploaded.name}:{uploaded.size}"
    staged = st.session_state.get("staged_video")

    if staged and staged["key"] == key and Path(staged["path"]).exists():
        return staged

    suffix = media.safe_suffix(uploaded.name, media.ALLOWED_VIDEO_EXTENSIONS)

    if suffix is None:
        st.error("That file type is not supported. Use MP4, AVI, MOV or MKV.")
        return None

    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    # The user's file name is never used on disk, only its extension.
    path = STAGING_DIR / f"input{suffix}"
    path.write_bytes(uploaded.getbuffer())

    properties = _read_properties(path)

    if properties is None:
        st.error(
            "That video could not be read. Try exporting it as an MP4 "
            "(H.264) file."
        )
        return None

    staged = {"key": key, "name": _clean_name(uploaded.name), **properties}
    st.session_state["staged_video"] = staged
    st.session_state.pop("video_result", None)

    return staged


def _stage_sample():
    key = f"sample:{SAMPLE_VIDEO.stat().st_size}"
    staged = st.session_state.get("staged_video")

    if staged and staged["key"] == key:
        return staged

    properties = _read_properties(SAMPLE_VIDEO)

    if properties is None:
        st.error("The sample video could not be read.")
        return None

    staged = {"key": key, "name": SAMPLE_VIDEO.name, **properties}
    st.session_state["staged_video"] = staged
    st.session_state.pop("video_result", None)

    return staged


# -- video: settings --------------------------------------------------------

def _settings_panel(run_options=True, default_camera="CAM-01",
                    camera_key="camera_id"):
    """Draw the settings widgets and return ``(settings, max_frames, live)``.

    ``run_options=False`` (the live camera page) leaves out the choices that
    only make sense for a finished file: how much to analyze and the
    live-feed switch.
    """

    settings = VideoSettings()

    with st.container(border=True):
        st.markdown("**Stop line and signal**")
        settings.stop_line_pct = st.slider(
            "Stop line (% from top)", 5, 95, 60, key="stop_line_pct",
            help="Drag until the red line sits on the stop line.",
        )
        mode = st.radio("Simulated signal", list(SIGNAL_MODES),
                        key="signal_mode")
        settings.signal_mode = SIGNAL_MODES[mode]

        if settings.signal_mode == "cycle":
            a, b = st.columns(2)
            settings.red_seconds = a.number_input(
                "Red (seconds)", 1, 300, 10, key="red_s")
            settings.green_seconds = b.number_input(
                "Green (seconds)", 1, 300, 10, key="green_s")

    with st.expander("Speed check"):
        settings.check_speed = st.checkbox(
            "Measure speed between two lines", key="check_speed",
            help="Needs the real distance between the lines.",
        )

        if settings.check_speed:
            a, b = st.columns(2)
            settings.speed_line_a_pct = a.slider(
                "Line A (% from top)", 5, 95, 45, key="line_a")
            settings.speed_line_b_pct = b.slider(
                "Line B (% from top)", 5, 95, 75, key="line_b")
            c, d = st.columns(2)
            settings.speed_distance_m = c.number_input(
                "Distance between lines (m)", 1.0, 500.0, 10.0, 0.5,
                key="distance_m",
                help="Measure it on the road. Speed is only as accurate as "
                     "this number.")
            settings.speed_limit_kmh = d.number_input(
                "Speed limit (km/h)", 5, 200, 40, key="limit_kmh")

    with st.expander("Wrong-way check"):
        settings.check_wrong_way = st.checkbox(
            "Flag vehicles moving against traffic", key="check_wrong_way")

        if settings.check_wrong_way:
            direction = st.selectbox(
                "Normal traffic moves", list(DIRECTIONS), key="direction")
            settings.expected_direction = DIRECTIONS[direction]
            lane = st.slider(
                "Lane to check (% from left)", 0, 100, (0, 100),
                key="lane_range",
                help="On a two-way road, shade only your side so oncoming "
                     "traffic is not flagged.")
            settings.lane_from_pct, settings.lane_to_pct = lane

    with st.expander("Collisions and alerts"):
        settings.check_collisions = st.checkbox(
            "Look for possible collisions", key="check_collisions",
            help="Needs overlapping vehicles that also slow down sharply.")

        configured = twilio_alert.is_configured()
        ready = twilio_alert.is_ready()
        settings.send_alerts = st.checkbox(
            "Send an SMS for each collision found", value=False,
            disabled=not (settings.check_collisions and ready),
            key="send_alerts",
        )

        if not configured:
            st.caption(
                "Twilio is not set up, so nothing will be sent. "
                "See the Alerts page."
            )
        elif not ready:
            st.caption(
                "Twilio settings need fixing before alerts can be sent: "
                + " ".join(twilio_alert.config_problems())
            )
        elif settings.send_alerts:
            st.warning(
                "A real message goes to the number in ALERT_TO_PHONE for "
                "every collision found. Turn this on only for footage you "
                "mean to alert about."
            )

    with st.expander("Emergency vehicles"):
        ready = EmergencyDetector.available()
        settings.use_emergency = st.checkbox(
            "Turn the simulated signal green for emergency vehicles",
            value=ready, disabled=not ready, key="video_emergency",
            help=None if ready else "Needs models/emergency_vehicle.pt.",
        )

        if not ready:
            st.caption("The emergency-vehicle model is not installed.")

    with st.expander("License plates"):
        available = plates.reader_available()
        settings.read_plates = st.checkbox(
            "Read the plate of each vehicle that breaks a rule",
            value=False, disabled=not available, key="read_plates",
            help=None if available else
            "Needs the optional plate reader: pip install -r "
            "requirements-plates.txt")

        if not available:
            st.caption(
                "The plate reader is not installed "
                "(`pip install -r requirements-plates.txt`).")
        else:
            st.caption(
                "Plates are personal data and OCR is often wrong on ordinary "
                "traffic video. Treat a plate as a suggestion to check "
                "against the evidence photo.")

    with st.container(border=True):
        st.markdown("**This run**")
        settings.camera_id = st.text_input(
            "Camera name", default_camera, max_chars=30, key=camera_key,
            help="Stored with every record and used in alerts.")
        max_frames, live = None, False

        if run_options:
            frames_label = st.selectbox(
                "How much to analyze", list(MAX_FRAME_CHOICES),
                key="max_frames")
            max_frames = MAX_FRAME_CHOICES[frames_label]
            live = st.checkbox("Show the live annotated feed", value=True,
                               key="live_feed")

        settings.save_to_db = st.checkbox(
            "Save results to the database", value=True, key="video_save",
            help="Adds records to the Dashboard, Evidence and Alerts pages.")

    return settings, max_frames, live


# -- video: tab -------------------------------------------------------------

def _video_tab():
    st.markdown(
        "Upload a clip from a **fixed camera**. Vehicles are detected and "
        "tracked, and the checks you turn on run on every frame. Each "
        "violation is saved with an annotated frame and a cropped photo."
    )

    uploaded = st.file_uploader(
        "Drop a traffic video here",
        type=[ext.lstrip(".") for ext in media.ALLOWED_VIDEO_EXTENSIONS],
        key="video_file",
        help="MP4, AVI, MOV or MKV, up to 200 MB. Clips of 10 to 60 "
             "seconds are fastest.",
    )

    use_sample = False

    if uploaded is None and SAMPLE_VIDEO.exists():
        if st.button("Try the sample video", key="btn_sample"):
            st.session_state["sample_selected"] = True

        use_sample = st.session_state.get("sample_selected", False)

    if uploaded is None and not use_sample:
        st.info("Upload a video to begin. MP4 (H.264) works best.")
        return

    staged = _stage_video(uploaded) if uploaded is not None else _stage_sample()

    if staged is None:
        return

    duration = staged["frames"] / staged["fps"] if staged["fps"] else 0

    st.markdown(
        theme.pill(staged["name"], "info")
        + theme.pill(f"{staged['width']} × {staged['height']} px", "info")
        + theme.pill(f"{staged['fps']:.0f} frames per second", "info")
        + theme.pill(f"{duration:.0f} seconds", "info"),
        unsafe_allow_html=True,
    )

    preview_col, settings_col = st.columns([3, 2])

    with settings_col:
        settings, max_frames, live = _settings_panel()

    problems = validate_settings(settings)

    height, width = staged["height"], staged["width"]
    speed_lines = (
        (pixel_row(height, settings.speed_line_a_pct),
         pixel_row(height, settings.speed_line_b_pct))
        if settings.check_speed else None
    )
    lane = (
        (pixel_col(width, settings.lane_from_pct),
         pixel_col(width, settings.lane_to_pct))
        if settings.check_wrong_way else None
    )

    with preview_col:
        st.caption("First frame, with your lines. Adjust the sliders until "
                   "they sit on the road.")
        show_image(
            draw_calibration(
                staged["first_frame"],
                pixel_row(height, settings.stop_line_pct),
                speed_lines, lane,
            ),
            channels="BGR",
        )

    for problem in problems:
        st.error(problem)

    if st.button("Run analysis", type="primary", key="run_video",
                 disabled=bool(problems)):
        _run_video(staged, settings, max_frames, live)

    result = st.session_state.get("video_result")

    if result:
        _show_video_result(result)


def _run_video(staged, settings, max_frames, live):
    models = _load_models(settings.use_emergency)

    if models is None:
        return

    detector, emergency = models
    plate_reader, plate_locator = (
        load_plate_tools() if settings.read_plates else (None, None))

    from app.tracking.tracker import VehicleTracker

    run_id = uuid.uuid4().hex[:8]
    run_dir = UPLOAD_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    processor = build_processor(
        settings, staged["width"], staged["height"],
        detector, VehicleTracker(), emergency, run_dir / "evidence",
        plate_reader=plate_reader, plate_locator=plate_locator,
    )

    bar = st.progress(0.0, text="Starting…")
    slot = st.empty() if live else None
    total = staged["frames"]
    limit = min(total, max_frames) if total and max_frames else (
        total or max_frames or 0
    )

    def on_progress(done, _total):
        fraction = min(1.0, done / limit) if limit else 0.0
        suffix = f" of {limit}" if limit else ""
        bar.progress(fraction, text=f"Analyzing frame {done}{suffix}")

    def on_frame(frame, number):
        show_image(frame, caption=f"Frame {number}", target=slot,
                   channels="BGR")

    try:
        summary = processor.process(
            staged["path"],
            run_dir / "annotated.mp4",
            show=False,
            progress=on_progress,
            source=f"upload:{staged['name']}",
            save_to_db=settings.save_to_db,
            max_frames=max_frames,
            run_id=run_id,
            frame_callback=on_frame if live else None,
        )

        bar.progress(1.0, text="Preparing the video for playback…")
        web_path = run_dir / "annotated_web.mp4"
        playable = media.to_browser_mp4(summary.output_path, web_path)
    except Exception as exc:
        bar.empty()

        if slot is not None:
            slot.empty()

        st.error(f"The analysis stopped: {exc}")
        return

    bar.empty()

    if slot is not None:
        slot.empty()

    audit.record(
        "analysis_run", user=(auth.current_user() or {}).get("name"),
        role=auth.current_role(), address=auth.client_address(),
        detail=f"{staged['name']}: {len(summary.violations)} violation(s), "
               f"{len(summary.collisions)} collision(s)")

    st.session_state["video_result"] = {
        "summary": summary,
        "playable": web_path if playable else None,
        "name": staged["name"],
        "settings": settings,
    }
    st.cache_data.clear()  # let the dashboard pick up the new records


# -- video: results ---------------------------------------------------------

def _violation_detail(violation, settings):
    if violation["type"] == "speeding":
        return (f"{violation['speed_kmh']:.1f} km/h "
                f"(limit {settings.speed_limit_kmh:g})")

    if violation["type"] == "red_light":
        return "Crossed the stop line on red"

    return "Moving against traffic"


def _show_video_result(result):
    summary = result["summary"]
    settings = result["settings"]

    st.divider()
    st.subheader("Results")

    realtime = summary.processing_fps >= summary.video_fps
    theme.gantry([
        ("Frames analyzed", summary.frames,
         f"{summary.duration_seconds:.1f} seconds of video", "white"),
        ("Processing speed", f"{summary.processing_fps:.1f} FPS",
         ("Faster than" if realtime else "Slower than")
         + f" the video's {summary.video_fps:.0f} FPS",
         "green" if realtime else "amber"),
        ("Violations", len(summary.violations),
         "red light, speeding, wrong way",
         "red" if summary.violations else "white"),
        ("Possible collisions", len(summary.collisions), "verify each one",
         "amber" if summary.collisions else "white"),
        ("Most vehicles in view", summary.peak_vehicles, "in a single frame",
         "white"),
        ("Emergency vehicles", len(summary.emergency_events),
         "signal turned green (simulated)",
         "green" if summary.emergency_events else "white"),
    ])

    if settings.save_to_db:
        st.caption("Saved to the database. Open the Dashboard, Evidence or "
                   "Alerts page to see it.")
    else:
        st.caption("Not saved to the database (turned off for this run).")

    tab_video, tab_violations, tab_collisions, tab_density, tab_emergency = (
        st.tabs([
            "Annotated video", "Violations", "Collisions",
            "Traffic density", "Emergency",
        ])
    )

    with tab_video:
        playable = result["playable"]

        if playable and playable.exists():
            video_bytes = playable.read_bytes()
            st.video(video_bytes)
            download_bytes, download_name = video_bytes, "annotated_traffic.mp4"
        else:
            st.info(
                "This computer cannot convert the video for playback in the "
                "browser. Install ffmpeg (`pip install imageio-ffmpeg`) to "
                "play it here. You can still download it."
            )
            download_bytes = summary.output_path.read_bytes()
            download_name = "annotated_traffic_raw.mp4"

        st.download_button("Download annotated video", data=download_bytes,
                           file_name=download_name, mime="video/mp4",
                           key="dl_video")

    with tab_violations:
        if not summary.violations:
            st.success(
                "No violations found with these settings. If you expected "
                "some, check the stop line, the signal setting and which "
                "checks are turned on."
            )
        else:
            table = pd.DataFrame([
                {
                    "Time (s)": v["time_seconds"],
                    "Type": VIOLATION_NAMES.get(v["type"], v["type"]),
                    "Track ID": v["track_id"],
                    "Vehicle": v["vehicle"],
                    "Detail": _violation_detail(v, settings),
                    "Frame": v["frame"],
                    **({"Plate": v.get("plate_text") or "unreadable"}
                       if settings.read_plates else {}),
                }
                for v in summary.violations
            ])
            show_df(table)
            st.download_button("Download violations (CSV)",
                               data=csv_bytes(table),
                               file_name="uploaded_video_violations.csv",
                               mime="text/csv", key="dl_video_violations")

            st.markdown("**Evidence (cropped vehicles)**")
            shown = summary.violations[:12]
            columns = st.columns(4)

            for i, violation in enumerate(shown):
                with columns[i % 4]:
                    show_image(
                        violation["crop_path"],
                        caption=(
                            f"{VIOLATION_NAMES.get(violation['type'])}, "
                            f"ID {violation['track_id']}, "
                            f"{violation['time_seconds']} s"
                        ),
                    )

            if len(summary.violations) > len(shown):
                st.caption(f"Showing {len(shown)} of "
                           f"{len(summary.violations)}. All are on the "
                           "Evidence page.")

    with tab_collisions:
        if not settings.check_collisions:
            st.info("Collision checking was off for this run. Turn it on "
                    "under “Collisions and alerts”.")
        elif not summary.collisions:
            st.success("No possible collisions found.")
        else:
            table = pd.DataFrame([
                {
                    "Time (s)": c["time_seconds"],
                    "Vehicles": " and ".join(f"ID {t}" for t in c["track_ids"]),
                    "Alert": c["alert_status"],
                    "Frame": c["frame"],
                }
                for c in summary.collisions
            ])
            show_df(table)
            st.warning("These are heuristic. Overlapping boxes plus a sharp "
                       "slowdown can still be something else. A person must "
                       "verify each one.")

            columns = st.columns(4)

            for i, collision in enumerate(summary.collisions[:8]):
                with columns[i % 4]:
                    show_image(
                        collision["crop_path"],
                        caption=f"{collision['time_seconds']} s",
                    )

    with tab_density:
        if not summary.density:
            st.info("No traffic density data.")
        else:
            density = pd.DataFrame(
                summary.density, columns=["Second", "Vehicles in view"]
            ).set_index("Second")
            st.line_chart(density)
            st.caption("Average number of tracked vehicles in each second "
                       "of video.")

    with tab_emergency:
        if not settings.use_emergency:
            st.info("Emergency detection was off for this run. It needs "
                    "models/emergency_vehicle.pt (see the README).")
        elif not summary.emergency_events:
            st.success("No emergency vehicle was confirmed in this video.")
        else:
            show_df(pd.DataFrame(summary.emergency_events))
            st.warning("Signal priority is simulated. No real signal was "
                       "controlled.")


def render():
    theme.page_head(
        "Analyze footage",
        "Upload traffic photos or a video from a fixed camera. Vehicles are "
        "detected and tracked, and violations are saved with evidence.",
    )

    if not auth.can("operate"):
        st.info("Your account can view results but not analyze footage. "
                "Ask an operator or admin to run an analysis.")
        return

    tab_video, tab_images, tab_help = st.tabs(["Video", "Images", "Tips"])

    with tab_video:
        _video_tab()

    with tab_images:
        _images_tab()

    with tab_help:
        st.markdown(
            """
**Get good results**
- Use a **fixed camera** with a clear view. Tracking, the stop line and the
  speed lines all assume the camera does not move.
- **Place the lines first.** Drag the sliders until the red stop line sits on
  the road's stop line in the preview.
- **The signal is simulated.** There is no live signal feed, so pick always
  red, always green or a red and green cycle. A red-light violation counts
  only while the signal is red.
- **Speed needs a real distance.** Measure the road between line A and line B.
  A wrong distance gives a wrong speed.
- **Wrong-way on a two-way road:** shade only your side of the road.
- **Collisions are a heuristic.** A person must verify every alert.

**Your files**
- Everything is processed on the computer running this app. Results and
  evidence are saved under `outputs/uploads/`.
- Collision alerts to Twilio are off unless you turn them on for a run.
            """
        )
