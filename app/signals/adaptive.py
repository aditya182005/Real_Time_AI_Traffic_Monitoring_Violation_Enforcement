"""Adaptive signal timing and a four-way junction simulator.

The idea: instead of giving every approach the same green time, give the
next green to the approach with the most waiting traffic (so long as nobody
has waited too long), and make the green as long as the queue needs.

    python -m app.signals.adaptive                 # compare fixed vs adaptive
    python -m app.signals.adaptive --seconds 3600 --seed 7 --rates 0.12,0.03,0.10,0.04

This is a *simulation* on made-up arrival rates. It shows the method works
on a model junction; it does not prove the same gain on a real road, and a
real signal is controlled by the road authority's own controller. Counts for
a real junction would come from ``traffic_density`` (vehicles per camera).
"""

import argparse
import random
import sys
from dataclasses import dataclass

APPROACHES = ("North", "East", "South", "West")


@dataclass
class Plan:
    min_green: int = 10
    max_green: int = 60
    seconds_per_vehicle: float = 2.0     # time one vehicle needs to clear
    lost_time: int = 4                   # amber and all-red between phases
    max_wait: int = 120                  # an approach this long waiting goes next


def green_time(queue, plan):
    """Green seconds an approach with ``queue`` vehicles waiting gets."""

    wanted = round(queue * plan.seconds_per_vehicle)

    return int(min(plan.max_green, max(plan.min_green, wanted)))


def next_approach(queues, waited, plan, current=None):
    """Index of the approach that should get the next green.

    An approach that has waited ``max_wait`` seconds or more goes first (the
    longest-waiting one if several); otherwise the longest queue wins, with
    ties going to whoever has waited longer. The approach that just had green
    is skipped while another has traffic.
    """

    count = len(queues)
    starving = [i for i in range(count) if waited[i] >= plan.max_wait
                and queues[i] > 0]

    if starving:
        return max(starving, key=lambda i: waited[i])

    candidates = [i for i in range(count) if i != current and queues[i] > 0]

    if not candidates:
        candidates = [i for i in range(count) if queues[i] > 0]

    if not candidates:
        return ((current + 1) % count) if current is not None else 0

    return max(candidates, key=lambda i: (queues[i], waited[i]))


@dataclass
class Result:
    name: str
    arrived: int
    served: int
    average_wait: float      # seconds, averaged over every vehicle that arrived
    longest_queue: int
    left_waiting: int


def simulate(controller, rates, seconds, seed=1, plan=None, fixed_green=30):
    """Run one junction. ``controller`` is "fixed" or "adaptive".

    Vehicles arrive randomly (each approach with probability ``rates[i]`` per
    second) and one leaves every ``seconds_per_vehicle`` while its approach
    is green. The same seed gives both controllers the same traffic.
    """

    plan = plan or Plan()
    rng = random.Random(seed)
    arrivals = [[rng.random() < rate for rate in rates] for _ in range(seconds)]
    count = len(rates)
    queues = [0] * count
    waited = [0] * count
    queue_seconds = 0
    arrived = served = longest = 0
    clock = 0
    current = None
    turn = 0

    while clock < seconds:
        if controller == "fixed":
            current, length = turn % count, fixed_green
            turn += 1
        else:
            current = next_approach(queues, waited, plan, current)
            length = green_time(queues[current], plan)

        credit = 0.0
        # green, then the lost time with everyone stopped
        for second in range(length + plan.lost_time):
            if clock >= seconds:
                break

            if second < length:
                credit += 1.0

                while credit >= plan.seconds_per_vehicle and queues[current]:
                    credit -= plan.seconds_per_vehicle
                    queues[current] -= 1
                    served += 1

            for i, arrives in enumerate(arrivals[clock]):
                if arrives:
                    queues[i] += 1
                    arrived += 1

            for i in range(count):
                if i == current and second < length:
                    waited[i] = 0                 # has the green
                elif queues[i]:
                    waited[i] += 1

            queue_seconds += sum(queues)
            longest = max(longest, max(queues))
            clock += 1

    return Result(controller, arrived, served,
                  round(queue_seconds / arrived, 1) if arrived else 0.0,
                  longest, sum(queues))


def compare(rates, seconds=1800, seed=1, plan=None):
    return [simulate(name, rates, seconds, seed, plan)
            for name in ("fixed", "adaptive")]


def report(results, rates, seconds):
    lines = [f"Junction simulation: {seconds} s, arrival chance per second "
             + ", ".join(f"{n} {r:.2f}" for n, r in zip(APPROACHES, rates)),
             f"{'controller':<10} {'arrived':>8} {'served':>7} "
             f"{'avg wait (s)':>13} {'longest queue':>14} {'left waiting':>13}"]

    for r in results:
        lines.append(f"{r.name:<10} {r.arrived:>8} {r.served:>7} "
                     f"{r.average_wait:>13} {r.longest_queue:>14} "
                     f"{r.left_waiting:>13}")

    fixed, adaptive = results

    if fixed.average_wait:
        change = (fixed.average_wait - adaptive.average_wait) \
            / fixed.average_wait * 100
        lines.append(f"Adaptive changes the average wait by {-change:+.0f}% "
                     "on this made-up traffic.")

    lines.append("This is a simulation, not a measurement of a real road.")

    return "\n".join(lines)


def parse_rates(text):
    try:
        rates = [float(x) for x in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError("rates must be numbers like 0.12,0.04,0.12,0.04")

    if len(rates) != 4 or any(not 0 <= r <= 1 for r in rates):
        raise argparse.ArgumentTypeError(
            "give four rates between 0 and 1 (North,East,South,West)")

    return rates


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m app.signals.adaptive", description=__doc__.split("\n")[0])
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--rates", type=parse_rates,
                        default=[0.12, 0.03, 0.10, 0.04],
                        help="chance a vehicle arrives each second, N,E,S,W")
    args = parser.parse_args(argv)

    if args.seconds < 60:
        parser.error("--seconds must be at least 60")

    print(report(compare(args.rates, args.seconds, args.seed),
                 args.rates, args.seconds))

    return 0


if __name__ == "__main__":
    sys.exit(main())
