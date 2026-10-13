"""Slow down password guessing (no Streamlit imports).

Failures are counted per username and per client address, for the whole
server process, so opening a new browser session does not reset them. After
``max_failures`` wrong attempts inside ``window`` seconds the key is locked
out; each repeat lockout lasts twice as long, up to ``max_lockout``.

Limits: the counts live in memory, so a restart clears them, and a client
address taken from a forwarded header is only as trustworthy as the proxy
that sets it. Also rate-limit at the reverse proxy (see DEPLOY.md).
"""

import threading
import time

MAX_KEYS = 10_000


class LoginLimiter:

    def __init__(self, max_failures=5, window=900, base_lockout=30,
                 max_lockout=900, clock=time.monotonic):
        self.max_failures = max_failures
        self.window = window
        self.base_lockout = base_lockout
        self.max_lockout = max_lockout
        self._clock = clock
        self._lock = threading.Lock()
        self._state = {}   # key -> {"fails": [times], "until": t, "strikes": n}

    def _entry(self, key):
        if key not in self._state and len(self._state) >= MAX_KEYS:
            # Drop the oldest entry rather than grow without limit.
            self._state.pop(next(iter(self._state)))

        return self._state.setdefault(
            key, {"fails": [], "until": 0.0, "strikes": 0})

    def seconds_locked(self, key):
        """How long this key must still wait (0 if it may try now)."""

        with self._lock:
            entry = self._state.get(key)

            if not entry:
                return 0

            return max(0, int(entry["until"] - self._clock() + 0.999))

    def record_failure(self, key):
        """Count a wrong attempt. Returns the lockout it caused, in seconds."""

        now = self._clock()

        with self._lock:
            entry = self._entry(key)
            entry["fails"] = [t for t in entry["fails"]
                              if now - t < self.window]
            entry["fails"].append(now)

            if len(entry["fails"]) < self.max_failures:
                return 0

            entry["strikes"] += 1
            duration = min(self.base_lockout * 2 ** (entry["strikes"] - 1),
                           self.max_lockout)
            entry["until"] = now + duration
            entry["fails"] = []

            return duration

    def record_success(self, key):
        with self._lock:
            self._state.pop(key, None)

    def reset(self):
        with self._lock:
            self._state.clear()


# One per server process. Addresses get a looser limit than usernames
# because many people can share one address (a campus, an office).
USER_LIMITER = LoginLimiter(max_failures=5)
ADDRESS_LIMITER = LoginLimiter(max_failures=25)


def locked_seconds(username, address):
    """Longest remaining wait across the username and address keys."""

    return max(
        USER_LIMITER.seconds_locked(f"user:{username}") if username else 0,
        ADDRESS_LIMITER.seconds_locked(f"ip:{address}") if address else 0,
    )


def record_failure(username, address):
    if username:
        USER_LIMITER.record_failure(f"user:{username}")

    if address:
        ADDRESS_LIMITER.record_failure(f"ip:{address}")


def record_success(username, address):
    if username:
        USER_LIMITER.record_success(f"user:{username}")

    # The address counter is kept: one good login must not erase an address
    # that has been guessing other accounts.
