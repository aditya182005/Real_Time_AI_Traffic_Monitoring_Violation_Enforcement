"""Traffic analytics from the records already in the database.

* congestion level by hour, from the average number of vehicles in view,
* vehicle counts by class,
* where in the frame violations happen (a grid for a heatmap).

"Congestion" here is vehicles in the camera's view, not road speed or length
of queue, and the thresholds depend on the camera's field of view: set them
for your camera (``CONGESTION_MODERATE`` / ``CONGESTION_HEAVY``).
"""

import os

import pandas as pd

LEVELS = ("Free", "Moderate", "Heavy")


def thresholds():
    def read(name, default):
        try:
            return float(os.getenv(name, default))
        except ValueError:
            return float(default)

    moderate = read("CONGESTION_MODERATE", 6)
    heavy = max(read("CONGESTION_HEAVY", 14), moderate)

    return moderate, heavy


def congestion_level(average_vehicles, moderate=None, heavy=None):
    """Free, Moderate or Heavy for an average count of vehicles in view."""

    if moderate is None or heavy is None:
        moderate, heavy = thresholds()

    if average_vehicles is None or pd.isna(average_vehicles):
        return None

    if average_vehicles >= heavy:
        return "Heavy"

    if average_vehicles >= moderate:
        return "Moderate"

    return "Free"


def congestion_by_hour(hourly):
    """Add a ``Level`` column to ``analytics.density_by_hour`` output.

    Hours with no data stay empty rather than reading as "Free".
    """

    table = hourly.copy()
    table["Level"] = [
        congestion_level(v) if v and not pd.isna(v) else None
        for v in table["Avg vehicles in view"]
    ]

    return table


def busiest_and_quietest(hourly):
    """``((hour, avg), (hour, avg))`` among hours with data, or None."""

    data = hourly[hourly["Avg vehicles in view"].fillna(0) > 0]

    if data.empty:
        return None

    top = data.loc[data["Avg vehicles in view"].idxmax()]
    low = data.loc[data["Avg vehicles in view"].idxmin()]

    return ((int(top["Hour (UTC)"]), float(top["Avg vehicles in view"])),
            (int(low["Hour (UTC)"]), float(low["Avg vehicles in view"])))


def class_totals(counts_df):
    """Distinct vehicles seen, by class, summed over runs."""

    if (counts_df is None or counts_df.empty
            or "vehicle_class" not in counts_df.columns):
        return pd.DataFrame(columns=["Vehicle class", "Vehicles"])

    totals = (
        pd.to_numeric(counts_df["vehicle_count"], errors="coerce")
        .groupby(counts_df["vehicle_class"]).sum().sort_values(ascending=False)
    )

    return (totals.astype(int).rename("Vehicles").rename_axis("Vehicle class")
            .reset_index())


def heatmap_grid(violations, bins=8):
    """A ``bins`` x ``bins`` table of violation counts by position in frame.

    Rows run top to bottom of the picture, columns left to right. Records
    without a position (older ones) are left out; returns None if none have
    one.
    """

    if (violations is None or violations.empty
            or not {"pos_x", "pos_y"} <= set(violations.columns)):
        return None

    x = pd.to_numeric(violations["pos_x"], errors="coerce")
    y = pd.to_numeric(violations["pos_y"], errors="coerce")
    ok = x.notna() & y.notna()

    if not ok.any():
        return None

    col = (x[ok].clip(0, 0.999999) * bins).astype(int)
    row = (y[ok].clip(0, 0.999999) * bins).astype(int)
    grid = pd.DataFrame(0, index=range(bins), columns=range(bins))

    for r, c in zip(row, col):
        grid.at[r, c] += 1

    return grid
