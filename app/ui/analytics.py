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


def alert_metrics(df):
    """Twilio success rate and latency (a metric in the project plan).

    Success rate is sent / (sent + failed): skipped and pending alerts were
    never attempted (or are not finished), so they do not count either way.
    Latency is from detection to Twilio's answer, for sent alerts only.
    """

    counts = alert_status_counts(df)
    attempted = counts["sent"] + counts["failed"]

    result = {
        "attempted": attempted,
        "success_rate": counts["sent"] / attempted if attempted else None,
        "median_ms": None,
        "slowest_ms": None,
    }

    if df.empty or not {"alert_status", "alert_latency_ms"} <= set(df.columns):
        return result

    sent = df[df["alert_status"].fillna("").astype(str).str.startswith("sent")]
    latency = pd.to_numeric(sent["alert_latency_ms"], errors="coerce").dropna()

    if not latency.empty:
        result["median_ms"] = float(latency.median())
        result["slowest_ms"] = float(latency.max())

    return result


def latest_row(df):
    """Most recent row by timestamp, or None."""

    if df.empty or "timestamp" not in df.columns:
        return None

    timestamps = _timestamps(df)

    if timestamps.isna().all():
        return None

    return df.loc[timestamps.idxmax()]


# -- overview helpers ---------------------------------------------------------

EVENT_NAMES = {
    "red_light": "Red light",
    "speeding": "Speeding",
    "wrong_way": "Wrong way",
}


def _where(row):
    for column in ("camera_id", "source"):
        value = row.get(column)

        if isinstance(value, str) and value:
            return value

    return ""


def recent_events(data, limit=10):
    """The newest events from every table, as one list for the overview.

    Columns: When (UTC), Event, Detail, Where. Newest first.
    """

    rows = []

    violations = data.get("violations")

    if violations is not None and not violations.empty:
        for _, row in violations.iterrows():
            kind = str(row.get("violation_type", ""))
            detail = []

            speed = pd.to_numeric(row.get("measured_speed"), errors="coerce")

            if kind == "speeding" and pd.notna(speed):
                detail.append(f"{speed:.0f} km/h")

            plate = row.get("plate_text")

            if isinstance(plate, str) and plate:
                detail.append(f"plate {plate}")

            detail.append(f"track {row.get('track_id', '?')}")
            rows.append((row.get("timestamp"),
                         EVENT_NAMES.get(kind, kind or "Violation"),
                         ", ".join(detail), _where(row)))

    collisions = data.get("collisions")

    if collisions is not None and not collisions.empty:
        for _, row in collisions.iterrows():
            status = str(row.get("alert_status") or "pending").split(":")[0]
            rows.append((
                row.get("timestamp"), "Possible collision",
                f"tracks {row.get('track_id_1', '?')} and "
                f"{row.get('track_id_2', '?')}, alert {status}",
                _where(row)))

    priority = data.get("priority")

    if priority is not None and not priority.empty:
        for _, row in priority.iterrows():
            rows.append((
                row.get("timestamp"), "Emergency vehicle",
                f"{row.get('vehicle_class', 'vehicle')}, confidence "
                f"{pd.to_numeric(row.get('confidence'), errors='coerce'):.2f}",
                _where(row)))

    table = pd.DataFrame(rows, columns=["When (UTC)", "Event", "Detail",
                                        "Where"])

    if table.empty:
        return table

    stamps = pd.to_datetime(table["When (UTC)"], errors="coerce", utc=True)
    table = table.assign(_t=stamps).sort_values("_t", ascending=False)
    table["When (UTC)"] = table["_t"].dt.strftime("%d %b %H:%M")

    return table.drop(columns="_t").head(limit).reset_index(drop=True)


def approved_fines(df):
    """Sum of fines on violations a person has approved."""

    if df.empty or "fine_amount" not in df.columns \
            or "review_status" not in df.columns:
        return 0

    approved = df[df["review_status"] == "approved"]

    return float(pd.to_numeric(
        approved["fine_amount"], errors="coerce").fillna(0).sum())


def pending_review_count(df):
    """Violations nobody has approved or rejected yet."""

    if df.empty:
        return 0

    if "review_status" not in df.columns:
        return len(df)

    return int((~df["review_status"].isin(["approved", "rejected"])).sum())


def attention_items(data, twilio_configured):
    """What a person should look at, as ``(kind, text)`` pairs.

    ``kind`` is a pill style: danger, warn, info or ok.
    """

    items = []
    collisions = data.get("collisions", pd.DataFrame())
    counts = alert_status_counts(collisions)

    if counts["failed"]:
        items.append(("danger", f"{counts['failed']} collision alert(s) "
                      "failed to send. Check the Twilio settings on the "
                      "Alerts page."))

    if len(collisions):
        items.append(("warn", f"{len(collisions)} possible collision(s) "
                      "need a person to verify the evidence."))

        if not twilio_configured:
            items.append(("info", "Twilio is not set up, so collision "
                          "alerts are skipped."))

    pending = pending_review_count(data.get("violations", pd.DataFrame()))

    if pending:
        items.append(("warn", f"{pending} violation(s) are waiting for a "
                      "person to review them on the Evidence page."))

    everything = [data.get(key) for key in
                  ("violations", "collisions", "priority", "density")]

    if all(df is None or df.empty for df in everything):
        items.append(("info", "No records in this period. Analyze footage "
                      "or widen the date range."))

    return items or [("ok", "Nothing needs attention in this period.")]


def peak_hour(density_df):
    """``(hour, average vehicles)`` of the busiest hour, or None."""

    table = density_by_hour(density_df)
    best = table["Avg vehicles in view"].max()

    if not best or pd.isna(best):
        return None

    hour = int(table.loc[table["Avg vehicles in view"].idxmax(), "Hour (UTC)"])

    return hour, float(best)
