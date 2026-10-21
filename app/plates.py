"""License-plate reading for vehicles that break a rule.

How it works
------------
1. Take the vehicle's crop (the box the tracker gave us).
2. Find the plate inside it: a small plate detector if
   ``models/plate_detector.pt`` exists, otherwise the lower part of the
   crop, where plates are.
3. Read the characters with an OCR engine (EasyOCR, optional).
4. Clean the text up and keep a few reads per vehicle. The text that most
   reads agree on wins, so one blurry frame cannot set the plate.

The OCR engine is optional and is passed in, so everything here can be
tested without it. Install it with ``pip install -r requirements/plates.txt``.

Honest limits: OCR on ordinary traffic footage is unreliable (small plates,
motion blur, angles, night). Treat a plate as a suggestion for a person to
check against the evidence image, never as proof. Plates are personal data:
see the retention setting in docs/DEPLOYMENT.md.
"""

import importlib.util
import os
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATE_DETECTOR_WEIGHTS = ROOT / "models" / "plate_detector.pt"

ALLOWED_CHARACTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

MIN_LENGTH = 4
MAX_LENGTH = 10

# Indian registration: state (2 letters), district (1-2 digits), series
# (0-3 letters), number (4 digits), e.g. KA01AB1234.
INDIAN_FORMAT = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}$")

# What OCR commonly confuses, for fixing a character in a known position.
TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
            "S": "5", "G": "6", "B": "8"}

# A correction that needs more changes than this is probably a wrong guess.
MAX_CORRECTIONS = 2

# Reads that do not fit the region's format count for less when voting.
UNFORMATTED_WEIGHT = 0.5


def region():
    """``IN`` (default) applies the Indian plate format; ``ANY`` does not."""

    value = os.getenv("PLATE_REGION", "IN").strip().upper()

    return value if value in ("IN", "ANY") else "IN"


def normalize(text):
    """Upper-case letters and digits only, or None if it cannot be a plate."""

    cleaned = re.sub(r"[^A-Z0-9]", "", str(text or "").upper())

    if not (MIN_LENGTH <= len(cleaned) <= MAX_LENGTH):
        return None

    if not any(c.isdigit() for c in cleaned):
        return None

    return cleaned


def _convert(char, table):
    return table.get(char, char)


def correct_indian(text):
    """Fix common OCR confusions using the Indian plate layout.

    Returns the corrected text if it can be made to fit the format with at
    most ``MAX_CORRECTIONS`` changes, otherwise None.
    """

    text = normalize(text)

    if text is None:
        return None

    if INDIAN_FORMAT.match(text):
        return text

    length = len(text)
    best = None

    for district in (1, 2):
        series = length - 6 - district

        if not 0 <= series <= 3:
            continue

        layout = (["letter"] * 2 + ["digit"] * district
                  + ["letter"] * series + ["digit"] * 4)
        changes = 0
        fixed = []

        for char, kind in zip(text, layout):
            wanted_letter = kind == "letter"

            if wanted_letter and char.isdigit():
                new = _convert(char, TO_LETTER)
            elif not wanted_letter and char.isalpha():
                new = _convert(char, TO_DIGIT)
            else:
                new = char

            # A confusion with no known substitute stays the wrong kind.
            if (new.isalpha() != wanted_letter):
                changes = MAX_CORRECTIONS + 1
                break

            changes += new != char
            fixed.append(new)

        if changes <= MAX_CORRECTIONS and (best is None or changes < best[0]):
            best = (changes, "".join(fixed))

    return best[1] if best else None


def clean_plate(text, plate_region=None):
    """Normalise a raw OCR string. Returns ``(text, fits_format)`` or None."""

    plate_region = plate_region or region()
    text = normalize(text)

    if text is None:
        return None

    if plate_region == "IN":
        corrected = correct_indian(text)

        if corrected is not None:
            return corrected, True

        return text, False

    return text, True


class PlateVotes:
    """Keeps the reads of each tracked vehicle and picks the best text."""

    def __init__(self, max_reads=3, plate_region=None):
        self.max_reads = max_reads
        self.region = plate_region or region()
        self._reads = defaultdict(list)     # track -> [(text, confidence, w)]
        self._attempts = defaultdict(int)

    def wants_more(self, track_id):
        return self._attempts[track_id] < self.max_reads

    def add(self, track_id, result):
        """``result`` is ``(text, confidence)`` from ``read_plate`` or None."""

        self._attempts[track_id] += 1

        if result is None:
            return

        text, confidence = result
        cleaned = clean_plate(text, self.region)

        if cleaned is None:
            return

        text, fits = cleaned
        weight = float(confidence) * (1.0 if fits else UNFORMATTED_WEIGHT)
        self._reads[track_id].append((text, float(confidence), weight))

    def best(self, track_id):
        """``(text, confidence)`` or None when nothing readable yet.

        The winner is the text with the largest total weight. Its
        confidence is the average confidence of the reads that agree.
        """

        reads = self._reads.get(track_id)

        if not reads:
            return None

        totals = defaultdict(float)

        for text, _, weight in reads:
            totals[text] += weight

        winner = max(totals, key=lambda t: (totals[t], t))
        agreeing = [c for t, c, _ in reads if t == winner]

        return winner, round(sum(agreeing) / len(agreeing), 3)


def prepare_for_ocr(image, min_width=240):
    """Grey, enlarge and boost contrast: small plates read much better."""

    import cv2

    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    height, width = image.shape[:2]

    if width < min_width:
        scale = min_width / float(width)
        image = cv2.resize(
            image, (min_width, max(1, int(height * scale))),
            interpolation=cv2.INTER_CUBIC,
        )

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))

    return clahe.apply(image)


def lower_region(vehicle_crop, fraction=0.55):
    """Where plates usually are when no plate detector is available."""

    height = vehicle_crop.shape[0]
    top = height - int(round(height * fraction))

    return vehicle_crop[top:height]


def read_plate(reader, vehicle_crop, locator=None):
    """Read the best plate text in one vehicle crop.

    ``reader.read(image)`` returns ``[(text, confidence), ...]``. ``locator``
    (optional) is ``locator(crop) -> [(x1, y1, x2, y2), ...]``. Returns
    ``(text, confidence)`` or None.
    """

    if vehicle_crop is None or vehicle_crop.size == 0:
        return None

    regions = []

    if locator is not None:
        for x1, y1, x2, y2 in locator(vehicle_crop):
            piece = vehicle_crop[int(y1):int(y2), int(x1):int(x2)]

            if piece.size:
                regions.append(piece)

    if not regions:
        regions = [lower_region(vehicle_crop)]

    best = None

    for piece in regions:
        pieces = list(reader.read(piece))

        # Two-row plates (motorcycles) come back as two pieces: also try
        # them joined.
        candidates = list(pieces)

        if len(pieces) > 1:
            joined = "".join(text for text, _ in pieces)
            mean = sum(conf for _, conf in pieces) / len(pieces)
            candidates.append((joined, mean))

        for text, confidence in candidates:
            cleaned = clean_plate(text)

            if cleaned is None:
                continue

            plate, fits = cleaned
            score = float(confidence) * (1.0 if fits else UNFORMATTED_WEIGHT)

            if best is None or score > best[0]:
                best = (score, plate, float(confidence))

    return None if best is None else (best[1], best[2])


# -- OCR engine and plate detector (optional) -------------------------------

class EasyOcrReader:
    """EasyOCR, limited to letters and digits."""

    def __init__(self, gpu=False):
        import easyocr

        self._reader = easyocr.Reader(["en"], gpu=gpu, verbose=False)

    @staticmethod
    def available():
        return importlib.util.find_spec("easyocr") is not None

    def read(self, image):
        results = self._reader.readtext(
            prepare_for_ocr(image),
            allowlist=ALLOWED_CHARACTERS,
            detail=1,
            paragraph=False,
        )

        return [(text, float(confidence)) for _, text, confidence in results]


class PlateDetector:
    """A YOLO model that finds plates inside a vehicle crop."""

    def __init__(self, weights=PLATE_DETECTOR_WEIGHTS, confidence=0.3):
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        self.confidence = confidence

    @staticmethod
    def available(weights=PLATE_DETECTOR_WEIGHTS):
        return Path(weights).is_file()

    def __call__(self, vehicle_crop):
        result = self.model(vehicle_crop, conf=self.confidence,
                            verbose=False)[0]

        return [tuple(map(float, box)) for box in result.boxes.xyxy.tolist()]


def reader_available():
    """True when plate reading is installed and not switched off."""

    if os.getenv("PLATE_OCR", "").strip().lower() == "off":
        return False

    return EasyOcrReader.available()


def load_tools():
    """``(reader, locator)`` for the pipeline; ``(None, None)`` if plate
    reading is not installed or is switched off.

    The locator is a plate-detector model when ``models/plate_detector.pt``
    exists, otherwise None (the lower part of the vehicle is read instead).
    """

    if not reader_available():
        return None, None

    reader = EasyOcrReader()
    locator = PlateDetector() if PlateDetector.available() else None

    return reader, locator
