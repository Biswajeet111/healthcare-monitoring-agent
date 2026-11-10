from datetime import datetime, timezone
from statistics import mean, median, stdev
from typing import Any
import math


class LongitudinalAnalysisError(ValueError):
    """Raised when longitudinal health data is invalid."""


def _parse_timestamp(value):
    try:
        if isinstance(value, datetime):
            timestamp = value
        elif isinstance(value, str):
            timestamp = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        else:
            raise ValueError("Unsupported timestamp type")

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        return timestamp

    except (ValueError, TypeError, OverflowError) as exc:
        raise LongitudinalAnalysisError(
            "Invalid measurement timestamp."
        ) from exc


def _validate_readings(readings):

    if not isinstance(readings, list):
        raise LongitudinalAnalysisError(
            "Readings must be provided as a list."
        )

    if len(readings) < 3:
        raise LongitudinalAnalysisError(
            "At least three readings are required."
        )

    parsed = []

    for index, reading in enumerate(readings):

        if not isinstance(reading, dict):
            raise LongitudinalAnalysisError(
                "Each reading must be a dictionary."
            )

        try:
            timestamp = _parse_timestamp(
                reading["recorded_at"]
            )

            value = float(reading["value"])

        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise LongitudinalAnalysisError(
                "Invalid measurement."
            ) from exc

        if not math.isfinite(value):
            raise LongitudinalAnalysisError(
                "Measurement values must be finite."
            )

        record_id = reading.get("id")

        if record_id is not None:
            if type(record_id) is not int or record_id <= 0:
                raise LongitudinalAnalysisError(
                    "Measurement ID must be a positive integer."
                )

        parsed.append({
            "recorded_at": timestamp,
            "value": value,
            "record_id": record_id,
            "original_index": index,
        })

        parsed.sort(
        key=lambda item: (
            item["recorded_at"],
            item["record_id"]
            if item["record_id"] is not None
            else item["original_index"],
        )
    )

    return parsed


def analyze_longitudinal_health(
    readings: list[dict[str, Any]],
    baseline_window: int = 5,
    recent_window: int = 3,
    anomaly_threshold: float = 2.0,
) -> dict[str, Any]:
    """
    Analyze historical measurements using:

    - Personal historical baseline
    - Recent rolling average
    - Absolute and percentage change
    - Statistical anomaly detection

    Statistical anomalies are not medical diagnoses.
    """

    parsed = _validate_readings(readings)

    if (
        isinstance(baseline_window, bool)
        or not isinstance(baseline_window, int)
        or baseline_window < 2
    ):
        raise LongitudinalAnalysisError(
            "baseline_window must be an integer >= 2."
        )

    if (
        isinstance(recent_window, bool)
        or not isinstance(recent_window, int)
        or recent_window < 1
    ):
        raise LongitudinalAnalysisError(
            "recent_window must be an integer >= 1."
        )

    if (
        isinstance(anomaly_threshold, bool)
        or not isinstance(anomaly_threshold, (int, float))
        or not math.isfinite(anomaly_threshold)
        or anomaly_threshold <= 0
    ):
        raise LongitudinalAnalysisError(
            "anomaly_threshold must be a positive finite number."
        )

    required = baseline_window + recent_window

    if len(parsed) < required:
        raise LongitudinalAnalysisError(
            f"At least {required} readings are required "
            "for the selected windows."
        )

    # Use non-overlapping historical and recent periods.
    baseline_readings = parsed[
        -(baseline_window + recent_window):-recent_window
    ]

    recent_readings = parsed[-recent_window:]

    baseline_values = [
        item["value"] for item in baseline_readings
    ]

    recent_values = [
        item["value"] for item in recent_readings
    ]

    baseline_mean = mean(baseline_values)
    baseline_median = median(baseline_values)
    baseline_std = stdev(baseline_values)

    recent_mean = mean(recent_values)
    latest_value = recent_values[-1]

    absolute_change = recent_mean - baseline_mean

    percentage_change = (
        absolute_change / abs(baseline_mean) * 100
        if baseline_mean != 0
        else None
    )

    if absolute_change > 0:
        direction = "increasing"
    elif absolute_change < 0:
        direction = "decreasing"
    else:
        direction = "unchanged"

    # Detect deviation relative to the historical baseline.
    # Zero variance means a z-score cannot be calculated.
    if baseline_std == 0:
        z_score = None
        is_anomaly = None
        anomaly_status = "insufficient_baseline_variability"
    else:
        z_score = (
            latest_value - baseline_mean
        ) / baseline_std

        is_anomaly = abs(z_score) >= anomaly_threshold

        anomaly_status = (
            "statistical_deviation_detected"
            if is_anomaly
            else "within_configured_threshold"
        )

    # Rolling averages across the selected historical series.
    all_values = [item["value"] for item in parsed]

    rolling_averages = []

    for index in range(recent_window - 1, len(parsed)):

        window_values = all_values[
            index - recent_window + 1:index + 1
        ]

        rolling_averages.append({
            "recorded_at": parsed[index][
                "recorded_at"
            ].isoformat(),
            "average": round(mean(window_values), 3),
        })

    return {
        "total_readings": len(parsed),

        "baseline": {
            "count": len(baseline_values),
            "mean": round(baseline_mean, 3),
            "median": round(baseline_median, 3),
            "standard_deviation": round(
                baseline_std, 3
            ),
            "start": baseline_readings[0][
                "recorded_at"
            ].isoformat(),
            "end": baseline_readings[-1][
                "recorded_at"
            ].isoformat(),
        },

        "recent": {
            "count": len(recent_values),
            "mean": round(recent_mean, 3),
            "latest_value": latest_value,
            "start": recent_readings[0][
                "recorded_at"
            ].isoformat(),
            "end": recent_readings[-1][
                "recorded_at"
            ].isoformat(),
        },

        "comparison": {
            "absolute_change": round(
                absolute_change, 3
            ),
            "percentage_change": (
                round(percentage_change, 3)
                if percentage_change is not None
                else None
            ),
            "direction": direction,
        },

        "anomaly": {
            "status": anomaly_status,
            "is_anomaly": is_anomaly,
            "z_score": (
                round(z_score, 3)
                if z_score is not None
                else None
            ),
            "threshold": anomaly_threshold,
        },

        "rolling_averages": rolling_averages,

        "disclaimer": (
            "This analysis identifies statistical changes "
            "in recorded measurements. It does not establish "
            "a medical diagnosis or determine clinical risk."
        ),
    }