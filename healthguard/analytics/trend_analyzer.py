from datetime import datetime, timezone
from statistics import mean, median, stdev
from typing import Any
import math


class TrendAnalysisError(ValueError):
    """Raised when health trend data is invalid."""


def analyze_health_trend(
    readings: list[dict[str, Any]],
) -> dict[str, Any]:

    if not isinstance(readings, list):
        raise TrendAnalysisError(
            "Readings must be provided as a list."
        )

    if len(readings) < 2:
        raise TrendAnalysisError(
            "At least two readings are required."
        )

    parsed_readings = []

    for reading in readings:

        if not isinstance(reading, dict):
            raise TrendAnalysisError(
                "Each reading must be a dictionary."
            )

        try:
            raw_date = reading["recorded_at"]

            if isinstance(raw_date, datetime):
                recorded_at = raw_date
            else:
                recorded_at = datetime.fromisoformat(
                    raw_date.replace("Z", "+00:00")
                )

            value = float(reading["value"])

        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            OverflowError,
        ) as exc:
            raise TrendAnalysisError(
                "Invalid reading date or value."
            ) from exc

        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(
                tzinfo=timezone.utc
            )
        else:
            recorded_at = recorded_at.astimezone(
                timezone.utc
            )

        if not math.isfinite(value):
            raise TrendAnalysisError(
                "Reading values must be finite."
            )

        parsed_readings.append({
            "recorded_at": recorded_at,
            "value": value,
        })

    # Deterministic ordering:
    # Chronological order first, value as tie-breaker.
    # Equal timestamps are ordered by value, not insertion order.
    parsed_readings.sort(
        key=lambda item: (
            item["recorded_at"],
            item["value"],
        )
    )

    values = [
        item["value"]
        for item in parsed_readings
    ]

    first_value = values[0]
    latest_value = values[-1]

    absolute_change = latest_value - first_value

    percentage_change = (
        (absolute_change / abs(first_value)) * 100
        if first_value != 0
        else None
    )

    if absolute_change > 0:
        direction = "increasing"
    elif absolute_change < 0:
        direction = "decreasing"
    else:
        direction = "unchanged"

    return {
        "count": len(values),
        "first_value": first_value,
        "latest_value": latest_value,
        "minimum": min(values),
        "maximum": max(values),
        "mean": round(mean(values), 3),
        "median": round(median(values), 3),
        "standard_deviation": round(stdev(values), 3),
        "absolute_change": round(absolute_change, 3),
        "percentage_change": (
            round(percentage_change, 3)
            if percentage_change is not None
            else None
        ),
        "direction": direction,
        "first_recorded_at": (
            parsed_readings[0]["recorded_at"].isoformat()
        ),
        "latest_recorded_at": (
            parsed_readings[-1]["recorded_at"].isoformat()
        ),
        "disclaimer": (
            "This analysis describes recorded measurements "
            "and does not establish a medical diagnosis."
        ),
    }