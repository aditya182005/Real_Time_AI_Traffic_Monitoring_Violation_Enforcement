"""Riders without a helmet: the matching and voting logic.

A helmet model (``models/helmet.pt``, see ``app/detection/helmet_detector.py``)
finds *heads* and says whether each wears a helmet. This module decides which
head belongs to which motorcycle and when enough frames agree to call it a
violation. It is plain Python so it can be tested without a model.

One frame saying "no helmet" is not enough: a hand, a hood or motion blur
fools a detector now and then. A rider is flagged only when ``confirm``
frames say "no helmet" and they outnumber the frames that say "helmet".
"""

NO_HELMET = "no_helmet"
HELMET = "helmet"


def head_belongs_to(head_box, bike_box, rise=0.9):
    """True if a head sits on the rider of this motorcycle.

    The head's centre must be within the bike's width and from ``rise`` bike
    heights above its top edge down to its vertical middle (riders sit above
    the machine; a passenger's head is higher still).
    """

    bx1, by1, bx2, by2 = bike_box
    hx = (head_box[0] + head_box[2]) / 2
    hy = (head_box[1] + head_box[3]) / 2
    height = max(1, by2 - by1)

    return (bx1 <= hx <= bx2
            and by1 - rise * height <= hy <= by1 + 0.5 * height)


class HelmetChecker:
    def __init__(self, confirm=3, min_confidence=0.5):
        self.confirm = max(1, int(confirm))
        self.min_confidence = min_confidence
        self._votes = {}       # track_id -> [helmet, no_helmet]
        self._flagged = set()

    def update(self, track_id, bike_box, heads):
        """Record this frame; True exactly once when the rider is confirmed.

        ``heads`` are dicts with ``bbox``, ``class_name`` ("helmet" or
        "no_helmet") and ``confidence``.
        """

        if track_id in self._flagged:
            return False

        votes = self._votes.setdefault(track_id, [0, 0])

        for head in heads:
            if head["confidence"] < self.min_confidence:
                continue

            if not head_belongs_to(head["bbox"], bike_box):
                continue

            votes[1 if head["class_name"] == NO_HELMET else 0] += 1

        if votes[1] >= self.confirm and votes[1] > votes[0]:
            self._flagged.add(track_id)

            return True

        return False
