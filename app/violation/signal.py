class SignalSimulator:
    """Software stand-in for a traffic signal (no real hardware is available).

    Either fixed on one state, or cycling RED -> GREEN on a timer measured in
    *video time*, so results do not depend on how fast the machine runs.
    """

    VALID_STATES = ("RED", "GREEN")

    def __init__(self, fixed=None, red_seconds=None, green_seconds=None,
                 start="RED"):
        if fixed is not None:
            if fixed not in self.VALID_STATES:
                raise ValueError(f"Signal must be one of {self.VALID_STATES}")
        else:
            if not red_seconds or not green_seconds:
                raise ValueError("A cycling signal needs red and green durations.")
            if red_seconds <= 0 or green_seconds <= 0:
                raise ValueError("Signal durations must be positive.")
            if start not in self.VALID_STATES:
                raise ValueError(f"start must be one of {self.VALID_STATES}")

        self.fixed_state = fixed
        self.red_seconds = red_seconds
        self.green_seconds = green_seconds
        self.start = start

    @classmethod
    def fixed(cls, state):
        return cls(fixed=state)

    @classmethod
    def cycle(cls, red_seconds, green_seconds, start="RED"):
        return cls(red_seconds=red_seconds, green_seconds=green_seconds,
                   start=start)

    def state_at(self, frame_number, fps):
        """Signal state for a 1-based frame number."""

        if self.fixed_state is not None:
            return self.fixed_state

        seconds = max(0.0, (frame_number - 1) / float(fps or 30))
        phase = seconds % (self.red_seconds + self.green_seconds)

        first, second = (
            ("RED", "GREEN") if self.start == "RED" else ("GREEN", "RED")
        )
        first_length = (
            self.red_seconds if self.start == "RED" else self.green_seconds
        )

        return first if phase < first_length else second

    def describe(self):
        if self.fixed_state is not None:
            return f"Always {self.fixed_state}"

        return (
            f"Cycle: {self.red_seconds:g}s red / "
            f"{self.green_seconds:g}s green"
        )
