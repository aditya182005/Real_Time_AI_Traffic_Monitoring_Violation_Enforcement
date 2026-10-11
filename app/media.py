"""Handling of user-uploaded files: validation, decoding, video conversion."""

import io
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
ALLOWED_VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv")

# Guards against "decompression bombs": a tiny file that declares an enormous
# image would otherwise allocate gigabytes when decoded.
MAX_IMAGE_PIXELS = 40_000_000


def safe_suffix(filename, allowed):
    """Return the file's extension if allowed, else None.

    Only the extension is taken from the user's filename, so uploaded names
    can never influence where files are written.
    """

    suffix = Path(str(filename)).suffix.lower()

    return suffix if suffix in allowed else None


def decode_image(data):
    """Decode image bytes to a BGR array.

    Raises ValueError for corrupt, unsupported or oversized images.
    """

    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except ImportError:
        width = height = 0
    except Exception as exc:
        raise ValueError("The file is not a readable image.") from exc

    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(
            f"Image is too large ({width}x{height}); "
            f"limit is {MAX_IMAGE_PIXELS // 1_000_000} megapixels."
        )

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("The file is not a readable image.")

    return image


def encode_image(image, extension=".jpg"):
    ok, buffer = cv2.imencode(extension, image)

    if not ok:
        raise ValueError("Could not encode image.")

    return buffer.tobytes()


def _ffmpeg_executable():
    exe = shutil.which("ffmpeg")

    if exe:
        return exe

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def to_browser_mp4(src, dst, timeout=900):
    """Re-encode a video to H.264 so browsers can play it.

    OpenCV usually writes MPEG-4 Part 2 ("mp4v"), which most browsers refuse
    to play inside ``st.video``. Returns True on success, False when ffmpeg
    is unavailable or fails (callers then offer a plain download).
    """

    exe = _ffmpeg_executable()

    if exe is None:
        return False

    command = [
        exe, "-y", "-loglevel", "error",
        "-i", str(src),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(dst),
    ]

    try:
        subprocess.run(
            command, check=True, capture_output=True, timeout=timeout
        )
    except (subprocess.SubprocessError, OSError):
        return False

    return Path(dst).exists() and Path(dst).stat().st_size > 0
