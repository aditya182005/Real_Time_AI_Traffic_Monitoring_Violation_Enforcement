"""Pure pandas helpers for the dashboard (no Streamlit imports)."""

import pandas as pd


def _timestamps(df):
    return pd.to_datetime(df["timestamp"], errors="coerce", utc=True)


def filter_by_date(df, start_date, end_date):
    """Keep rows whose timestamp is within the dates (end date inclusive)."""

    if df.empty or "timestamp" not in df.columns:
        return df.copy()

    start = pd.Timestamp(start_date, tz="UTC")
    end = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)
    timestamps = _timestamps(df)

    return df.loc[timestamps.ge(start) & timestamps.lt(end)].copy()


def by_type(df, violation_type):
    if df.empty or "violation_type" not in df.columns:
        return df.iloc[0:0].copy()

    return df[df["violation_type"].astype(str) == violation_type].copy()


def _hour_table(hours, values, column):
    table = pd.DataFrame({"Hour (UTC)": range(24)})
    series = pd.Series(values, index=hours)

    table[column] = (
        table["Hour (UTC)"].map(series).fillna(0)
    )

    return table


def violations_per_hour(df):
    """Violations grouped by hour of day, always 24 rows (0-23, UTC)."""

    if df.empty or "timestamp" not in df.columns:
        return _hour_table([], [], "Violations")

    hours = _timestamps(df).dt.hour.dropna().astype(int)
    counts = hours.value_counts()

    table = _hour_table(counts.index, counts.values, "Violations")
    table["Violations"] = table["Violations"].astype(int)

    return table


def violations_by_type(df):
    if df.empty or "violation_type" not in df.columns:
        return pd.DataFrame(columns=["Violation type", "Count"])

    counts = (
        df["violation_type"].fillna("unknown").astype(str)
        .value_counts()
        .rename_axis("Violation type")
        .reset_index(name="Count")
    )

    return counts


def density_by_hour(df):
    """Average vehicles in view per hour of day (0-23, UTC)."""

    if (
        df.empty
        or "timestamp" not in df.columns
        or "vehicle_count" not in df.columns
    ):
        return _hour_table([], [], "Avg vehicles in view")

    frame = pd.DataFrame({
        "hour": _timestamps(df).dt.hour,
        "count": pd.to_numeric(df["vehicle_count"], errors="coerce"),
    }).dropna()

    means = frame.groupby("hour")["count"].mean()

    return _hour_table(
        means.index.astype(int), means.values, "Avg vehicles in view"
    ).round(2)


def total_fines(df):
    if df.empty or "fine_amount" not in df.columns:
        return 0

    return float(
        pd.to_numeric(df["fine_amount"], errors="coerce").fillna(0).sum()
    )


def alert_status_counts(df):
    """Twilio outcome counts, grouped into sent / skipped / failed / pending."""

    result = {"sent": 0, "skipped": 0, "failed": 0, "pending": 0}

    if df.empty or "alert_status" not in df.columns:
        return result

    for value in df["alert_status"].fillna("pending").astype(str):
        key = value.split(" ")[0].split(":")[0].lower()
        result[key if key in result else "pending"] += 1

    return result


def latest_row(df):
    """Most recent row by timestamp, or None."""

    if df.empty or "timestamp" not in df.columns:
        return None

    timestamps = _timestamps(df)

    if timestamps.isna().all():
        return None

    return df.loc[timestamps.idxmax()]
