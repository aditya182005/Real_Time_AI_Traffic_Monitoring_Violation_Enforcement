"""A simulated signal whose green time follows the live queue.

The camera watches one approach of a four-way junction. Each frame the video
processor tells this signal how many vehicles are waiting before the stop
line (``observe_queue``); when this approach's green starts, its length is
chosen with the same ``green_time`` rule as the adaptive simulator. The other
three approaches are not filmed, so they are modelled as arriving at the given
rates (vehicles per second) and getting their own adaptive greens in turn.

It is a simulation of the timing method, driven by real counts for one
approach. It does not control a real signal.
"""

from app.signals.adaptive import APPROACHES, Plan, green_time

DEFAULT_OTHER_RATES = (0.03, 0.10, 0.04)    # the other three approaches


class AdaptiveSignal:
    label = "adaptive, from live counts"
    predictable = False      # depends on the traffic, so cannot be looked ahead

    def __init__(self, plan=None, other_rates=DEFAULT_OTHER_RATES, start="RED"):
        if len(other_rates) != len(APPROACHES) - 1:
            raise ValueError("Give the arrival rate of the other 3 approaches.")

        self.plan = plan or Plan()
        self.other_rates = tuple(other_rates)
        self.queue = 0
        self._state = start
        self._end = None             # video seconds when this phase ends
        self._last_green = [0.0] * len(other_rates)
        self.greens = []             # (start_seconds, length) of our greens

    def observe_queue(self, count):
        self.queue = max(0, int(count))

    def _red_length(self, now):
        """How long the other three approaches hold the junction."""

        total = 0.0

        for i, rate in enumerate(self.other_rates):
            waited = now - self._last_green[i]
            guess = min(30, round(rate * max(0.0, waited)))
            length = green_time(guess, self.plan)
            total += length + self.plan.lost_time
            self._last_green[i] = now + total

        return total

    def state_at(self, frame_number, fps):
        now = max(0.0, (frame_number - 1) / float(fps or 30))

        if self._end is None:       # first call: start the first phase
            self._end = now + (
                self._red_length(now) if self._state == "RED"
                else green_time(self.queue, self.plan)
            )

        while now >= self._end:
            if self._state == "RED":
                length = green_time(self.queue, self.plan)
                self.greens.append((round(self._end, 1), length))
                self._state = "GREEN"
                self._end += length
            else:
                self._state = "RED"
                self._end += self._red_length(self._end)

        return self._state

    def describe(self):
        return (f"Adaptive: green {self.plan.min_green}-{self.plan.max_green}s "
                f"by live queue")
