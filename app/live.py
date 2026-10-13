"""Live camera input: RTSP / HTTP streams and webcams.

Two pieces:

``LatestFrameCapture``
    Reads the stream on its own thread and keeps only the newest frame. If
    detection is slower than the camera, old frames are dropped instead of
    queueing up, so the analysis stays close to real time. A broken
    connection is retried; after too many failures in a row it gives up.

``LiveMonitor``
    Runs the normal analysis pipeline on a camera in a background thread, so
    monitoring keeps going when the browser tab is closed. The dashboard
    only starts it, stops it and shows its latest frame and counters.

Time comes from the wall clock, not from counting frames, so speed and
signal timing stay correct even when frames are dropped.

Security: a stream address can point the server at any host it can reach.
In production only cameras named in ``LIVE_CAMERAS`` can be used, unless
``LIVE_ALLOW_CUSTOM=true``. Addresses often contain a camera password, so
they are never shown or logged; only ``redact`` output is.
"""

import logging
import os
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

import cv2

from app import env, paths

log = logging.getLogger("traffic_agent.live")

STREAM_SCHEMES = ("rtsp", "rtsps", "http", "https", "rtmp")

# Cameras often report 0 or a nonsense frame rate (e.g. 90000 for RTSP).
DEFAULT_FPS = 25.0
MAX_SANE_FPS = 120.0


# -- sources ----------------------------------------------------------------

def parse_source(text):
    """Turn what the user typed into something ``cv2.VideoCapture`` opens.

    A whole number is a webcam index; an rtsp/http(s)/rtmp address is a
    stream. Anything else (file paths, other schemes) is rejected so a user
    cannot make the server open arbitrary local files.
    """

    text = str(text if text is not None else "").strip()

    if not text:
        raise ValueError("Enter a camera address or choose a camera.")

    if text.isdigit():
        return int(text)

    parts = urlsplit(text)

    if parts.scheme.lower() not in STREAM_SCHEMES or not parts.hostname:
        raise ValueError(
            "The address must start with rtsp://, rtsps://, http://, "
            "https:// or rtmp://, or be a webcam number such as 0."
        )

    return text


def redact(source):
    """The source with any password removed, safe to show or log."""

    if isinstance(source, int):
        return f"webcam {source}"

    parts = urlsplit(str(source))

    if parts.password or parts.username:
        host = parts.hostname or ""

        if parts.port:
            host = f"{host}:{parts.port}"

        parts = parts._replace(netloc=f"***@{host}")

    return urlunsplit(parts)


def configured_cameras():
    """Named cameras from ``LIVE_CAMERAS="Gate=rtsp://...;Junction=rtsp://..."``.

    Returns ``{name: address}``. Entries that are malformed are ignored.
    """

    cameras = {}

    for item in os.getenv("LIVE_CAMERAS", "").split(";"):
        name, _, address = item.partition("=")
        name, address = name.strip(), address.strip()

        if not name or not address:
            continue

        try:
            parse_source(address)
        except ValueError:
            continue

        cameras[name] = address

    return cameras


def custom_addresses_allowed():
    """Free-form addresses: always on a developer machine, opt-in on a server."""

    if not env.is_production():
        return True

    return os.getenv("LIVE_ALLOW_CUSTOM", "").strip().lower() in (
        "1", "true", "yes")


# -- capture ----------------------------------------------------------------

class LatestFrameCapture:
    """A ``cv2.VideoCapture`` stand-in that always returns the newest frame."""

    def __init__(self, source, opener=cv2.VideoCapture, reconnect_delay=2.0,
                 max_failures=10, read_timeout=1.0, sleep=None):
        self.source = source
        self._opener = opener
        self._reconnect_delay = reconnect_delay
        self._max_failures = max_failures
        self._read_timeout = read_timeout
        self._stop = threading.Event()
        # Waiting on the stop flag makes a retry pause end the moment we stop.
        self._sleep = sleep or self._stop.wait

        self._lock = threading.Condition()
        self._frame = None
        self._sequence = 0          # frames received
        self._delivered = 0         # sequence number last handed out
        self._finished = False
        self.status = "connecting"
        self.reconnects = 0
        self.dropped = 0
        self.last_error = ""
        self._width = 0
        self._height = 0
        self._fps = DEFAULT_FPS

        self._thread = threading.Thread(
            target=self._run, name="live-capture", daemon=True)
        self._thread.start()

    # -- background reader --------------------------------------------------

    def _run(self):
        failures = 0
        cap = None

        try:
            while not self._stop.is_set():
                try:
                    if cap is None:
                        cap = self._opener(self.source)

                        if not cap.isOpened():
                            raise ConnectionError(
                                "could not open the camera")

                        self._learn_properties(cap)

                    ok, frame = cap.read()

                    if not ok or frame is None:
                        raise ConnectionError(
                            "the stream stopped sending frames")
                except Exception as exc:
                    # Camera libraries fail in many ways; every one of them
                    # means "close it and try again".
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass

                    cap = None
                    failures += 1
                    message = (
                        str(exc) if isinstance(exc, ConnectionError)
                        else f"{type(exc).__name__}: {exc}")
                    # An error message may quote the address, password and all.
                    self.last_error = message.replace(
                        str(self.source), redact(self.source))

                    if not self._give_up_or_wait(failures):
                        return

                    continue

                if failures:
                    log.info("camera back after %d failed attempt(s)",
                             failures)

                failures = 0
                self.status = "running"

                with self._lock:
                    if self._sequence > self._delivered:
                        self.dropped += 1   # newest frame was never used

                    self._frame = frame
                    self._sequence += 1
                    self._lock.notify_all()
        finally:
            if cap is not None:
                cap.release()

            with self._lock:
                self._finished = True
                self.status = (
                    "stopped" if self._stop.is_set() else self.status)
                self._lock.notify_all()

    def _give_up_or_wait(self, failures):
        """Returns False when it is time to stop trying."""

        if failures >= self._max_failures:
            self.status = "lost"
            log.error("giving up on the camera after %d attempts: %s",
                      failures, self.last_error)
            return False

        self.status = "reconnecting"
        self.reconnects += 1
        log.warning("camera problem (%s); retry %d of %d",
                    self.last_error, failures, self._max_failures)
        self._sleep(self._reconnect_delay)

        return True

    def _learn_properties(self, cap):
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = cap.get(cv2.CAP_PROP_FPS) or 0

        if width and height:
            self._width, self._height = width, height

        if 0 < fps <= MAX_SANE_FPS:
            self._fps = float(fps)

    # -- the cv2.VideoCapture-like surface ------------------------------------

    @property
    def finished(self):
        """True once the reader has stopped for good (stopped or lost)."""

        return self._finished

    def isOpened(self):
        return not self._finished

    def read(self):
        """Wait up to ``read_timeout`` for a frame newer than the last one.

        Returns ``(True, frame)`` or ``(False, None)`` on timeout or when
        finished. Check ``finished`` to tell those apart.
        """

        with self._lock:
            self._lock.wait_for(
                lambda: self._sequence > self._delivered or self._finished,
                timeout=self._read_timeout,
            )

            if self._sequence > self._delivered:
                self._delivered = self._sequence
                return True, self._frame

        return False, None

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self._width

        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return self._height

        if prop == cv2.CAP_PROP_FPS:
            return self._fps

        return 0

    def wait_for_first_frame(self, timeout=15.0):
        """Block until a frame has arrived. Returns True if one did."""

        with self._lock:
            self._lock.wait_for(
                lambda: self._sequence > 0 or self._finished, timeout=timeout)

            return self._sequence > 0

    def release(self):
        self._stop.set()

        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)


# -- background monitor -----------------------------------------------------

class LiveMonitor:
    """Runs the analysis pipeline on a camera until stopped.

    One monitor runs at most one camera. ``detector``, ``tracker`` and
    ``capture_factory`` can be replaced in tests.
    """

    def __init__(self, settings, name, source, detector, tracker,
                 emergency_detector=None, plate_reader=None,
                 plate_locator=None, capture_factory=LatestFrameCapture,
                 max_seconds=None):
        self.settings = settings
        self.name = name
        self.source = source
        self._detector = detector
        self._tracker = tracker
        self._emergency = emergency_detector
        self._plate_reader = plate_reader
        self._plate_locator = plate_locator
        self._capture_factory = capture_factory
        self._max_seconds = max_seconds

        self.run_id = uuid.uuid4().hex[:8]
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._jpeg = None
        self._last_preview = 0.0

        self.state = "starting"   # starting | running | stopped | failed
        self.error = ""
        self.started_at = None
        self.frames = 0
        self.violations = 0
        self.collisions = 0
        self.recent = []          # newest-first event descriptions
        self.summary = None
        self._capture = None

    # -- control ------------------------------------------------------------

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name=f"live-{self.run_id}", daemon=True)
        self._thread.start()

    def stop(self, wait=10):
        self._stop.set()

        if self._thread is not None and wait:
            self._thread.join(timeout=wait)

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    # -- the worker ---------------------------------------------------------

    def _run(self):
        from app.analysis import build_processor

        capture = None

        try:
            capture = self._capture_factory(self.source)
            self._capture = capture

            if not capture.wait_for_first_frame():
                raise ConnectionError(
                    "no picture arrived from the camera "
                    f"({capture.last_error or 'timed out'})"
                )

            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

            processor = build_processor(
                self.settings, width, height, self._detector, self._tracker,
                self._emergency,
                paths.OUTPUT_DIR / "live" / self.run_id,
                plate_reader=self._plate_reader,
                plate_locator=self._plate_locator,
            )

            self.started_at = time.time()
            self.state = "running"
            log.info("live monitoring started: %s (%s)",
                     self.name, redact(self.source))

            self.summary = processor.process(
                None, None,
                capture=capture,
                live=True,
                stop_event=self._stop,
                max_seconds=self._max_seconds,
                show=False,
                source=f"live:{self.name}",
                save_to_db=self.settings.save_to_db,
                run_id=self.run_id,
                frame_callback=self._on_frame,
                preview_every=1,
                on_event=self._on_event,
            )

            if capture.status == "lost" and not self._stop.is_set():
                self.state = "failed"
                self.error = f"lost the camera ({capture.last_error})"
                log.error("live monitoring ended: %s", self.error)
            else:
                self.state = "stopped"
                log.info("live monitoring stopped: %s", self.name)
        except Exception as exc:  # the thread must never die silently
            self.state = "failed"
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("live monitoring crashed")
        finally:
            if capture is not None:
                capture.release()

    def _on_frame(self, frame, frame_number):
        self.frames = frame_number
        now = time.monotonic()

        # Encoding is not free; about two previews a second is plenty.
        if now - self._last_preview < 0.5:
            return

        self._last_preview = now
        ok, buffer = cv2.imencode(".jpg", frame,
                                  [cv2.IMWRITE_JPEG_QUALITY, 70])

        if ok:
            with self._lock:
                self._jpeg = buffer.tobytes()

    def _on_event(self, kind, entry):
        if kind == "collision":
            self.collisions += 1
            text = f"possible collision, tracks {entry['track_ids']}"
        else:
            self.violations += 1
            text = f"{entry['type']}, track {entry['track_id']}"

            if entry.get("plate_text"):
                text += f", plate {entry['plate_text']}"

        with self._lock:
            self.recent.insert(0, text)
            del self.recent[20:]

    # -- what the dashboard reads -----------------------------------------

    def latest_jpeg(self):
        with self._lock:
            return self._jpeg

    def snapshot(self):
        """A plain dict of the current state for display."""

        capture = self._capture
        elapsed = (time.time() - self.started_at) if self.started_at else 0

        with self._lock:
            recent = list(self.recent)

        return {
            "camera": self.name,
            "state": self.state,
            "connection": capture.status if capture else "connecting",
            "reconnects": capture.reconnects if capture else 0,
            "dropped_frames": capture.dropped if capture else 0,
            "frames_analyzed": self.frames,
            "analysis_fps": round(self.frames / elapsed, 1) if elapsed else 0,
            "violations": self.violations,
            "collisions": self.collisions,
            "running_seconds": int(elapsed),
            "recent": recent,
            "error": self.error,
        }


# -- the monitors running in this server process --------------------------------

class LiveError(RuntimeError):
    """A live camera could not be started (worded for the person)."""


def max_cameras():
    try:
        return max(1, int(os.getenv("LIVE_MAX_CAMERAS", "1")))
    except ValueError:
        return 1


class MonitorRegistry:
    """Monitors outlive browser sessions, so they are kept here.

    Streamlit re-runs a page's script on every click, and each browser tab
    is its own session; the camera loop must belong to neither. Cameras
    that have ended stay listed (so their result can be read) until the
    same name is started again.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._monitors = {}

    def start(self, name, source, settings, detector, tracker,
              emergency_detector=None, plate_reader=None, **options):
        with self._lock:
            current = self._monitors.get(name)

            if current is not None and current.active:
                raise LiveError(f"{name} is already running.")

            running = sum(1 for m in self._monitors.values() if m.active)

            if running >= max_cameras():
                raise LiveError(
                    f"Only {max_cameras()} camera(s) can run at once on "
                    "this server. Stop one first.")

            monitor = LiveMonitor(
                settings, name, source, detector, tracker,
                emergency_detector=emergency_detector,
                plate_reader=plate_reader, **options)
            self._monitors[name] = monitor
            monitor.start()

            return monitor

    def get(self, name):
        with self._lock:
            return self._monitors.get(name)

    def names(self):
        with self._lock:
            return list(self._monitors)

    def stop(self, name, wait=10):
        monitor = self.get(name)

        if monitor is not None:
            monitor.stop(wait=wait)

    def stop_all(self, wait=10):
        with self._lock:
            monitors = list(self._monitors.values())

        for monitor in monitors:
            monitor.stop(wait=wait)

    def snapshots(self):
        with self._lock:
            monitors = list(self._monitors.values())

        return [m.snapshot() for m in monitors]

    def clear(self):
        """Forget finished monitors (tests, or after stop_all)."""

        with self._lock:
            self._monitors = {
                n: m for n, m in self._monitors.items() if m.active}


REGISTRY = MonitorRegistry()
