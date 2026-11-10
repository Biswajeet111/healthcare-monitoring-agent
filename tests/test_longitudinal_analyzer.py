from datetime import datetime, timedelta, timezone

import pytest

from healthguard.analytics.longitudinal_analyzer import (
    analyze_longitudinal_health,
    LongitudinalAnalysisError,
)


def make_readings(values):

    start = datetime(
        2026, 11, 1, 10, 0, tzinfo=timezone.utc
    )

    return [
        {
            "recorded_at": (
                start + timedelta(days=index)
            ).isoformat(),
            "value": value,
        }
        for index, value in enumerate(values)
    ]


def test_increasing_longitudinal_trend():

    readings = make_readings([
        100, 102, 101, 103, 104,
        115, 120, 125,
    ])

    result = analyze_longitudinal_health(readings)

    assert result["total_readings"] == 8
    assert result["baseline"]["count"] == 5
    assert result["recent"]["count"] == 3

    assert result["comparison"]["direction"] == "increasing"
    assert result["comparison"]["absolute_change"] > 0


def test_decreasing_longitudinal_trend():

    readings = make_readings([
        120, 122, 121, 123, 124,
        110, 105, 100,
    ])

    result = analyze_longitudinal_health(readings)

    assert result["comparison"]["direction"] == "decreasing"


def test_unchanged_longitudinal_trend():

    readings = make_readings([100] * 8)

    result = analyze_longitudinal_health(readings)

    assert result["comparison"]["direction"] == "unchanged"
    assert result["comparison"]["absolute_change"] == 0


def test_statistical_anomaly_detected():

    readings = make_readings([
        100, 101, 99, 100, 102,
        105, 110, 150,
    ])

    result = analyze_longitudinal_health(readings)

    assert result["anomaly"]["is_anomaly"] is True
    assert (
        result["anomaly"]["status"]
        == "statistical_deviation_detected"
    )


def test_no_statistical_anomaly():

    readings = make_readings([
        100, 105, 95, 102, 98,
        100, 101, 102,
    ])

    result = analyze_longitudinal_health(readings)

    assert result["anomaly"]["is_anomaly"] is False


def test_zero_variance_baseline():

    readings = make_readings([
        100, 100, 100, 100, 100,
        110, 120, 130,
    ])

    result = analyze_longitudinal_health(readings)

    assert result["anomaly"]["is_anomaly"] is None
    assert result["anomaly"]["z_score"] is None

    assert (
        result["anomaly"]["status"]
        == "insufficient_baseline_variability"
    )


def test_insufficient_readings():

    readings = make_readings([100, 110, 120])

    with pytest.raises(LongitudinalAnalysisError):
        analyze_longitudinal_health(readings)


def test_invalid_baseline_window():

    readings = make_readings([100] * 8)

    with pytest.raises(LongitudinalAnalysisError):
        analyze_longitudinal_health(
            readings,
            baseline_window=1,
        )


def test_invalid_recent_window():

    readings = make_readings([100] * 8)

    with pytest.raises(LongitudinalAnalysisError):
        analyze_longitudinal_health(
            readings,
            recent_window=0,
        )


def test_invalid_anomaly_threshold():

    readings = make_readings([100] * 8)

    with pytest.raises(LongitudinalAnalysisError):
        analyze_longitudinal_health(
            readings,
            anomaly_threshold=0,
        )


def test_non_finite_measurement():

    readings = make_readings([
        100, 101, 102, 103,
        104, 105, float("nan"), 107,
    ])

    with pytest.raises(LongitudinalAnalysisError):
        analyze_longitudinal_health(readings)


def test_rolling_average_count():

    readings = make_readings([
        100, 101, 102, 103,
        104, 105, 106, 107,
    ])

    result = analyze_longitudinal_health(readings)

    assert len(result["rolling_averages"]) == 6


def test_unsorted_readings():

    readings = make_readings([
        100, 101, 102, 103,
        104, 105, 106, 107,
    ])

    reversed_readings = list(reversed(readings))

    result = analyze_longitudinal_health(
        reversed_readings
    )

    assert result["recent"]["latest_value"] == 107


def test_mixed_timezone_timestamps():

    readings = make_readings([
        100, 101, 102, 103,
        104, 105, 106, 107,
    ])

    readings[0]["recorded_at"] = (
        "2026-11-01T15:30:00+05:30"
    )

    result = analyze_longitudinal_health(readings)

    assert result["total_readings"] == 8


def test_zero_baseline_mean():

    readings = make_readings([
        0, 0, 0, 0, 0,
        10, 20, 30,
    ])

    result = analyze_longitudinal_health(readings)

    assert result["comparison"]["percentage_change"] is None

def test_identical_timestamps_ordered_by_database_id():

    readings = [
        {
            "id": 3,
            "recorded_at": "2026-11-10T10:00:00",
            "value": 130,
        },
        {
            "id": 1,
            "recorded_at": "2026-11-10T10:00:00",
            "value": 100,
        },
        {
            "id": 2,
            "recorded_at": "2026-11-10T10:00:00",
            "value": 110,
        },
        {
            "id": 4,
            "recorded_at": "2026-11-10T10:00:00",
            "value": 140,
        },
        {
            "id": 5,
            "recorded_at": "2026-11-10T10:00:00",
            "value": 150,
        },
    ]

    result = analyze_longitudinal_health(
        readings,
        baseline_window=3,
        recent_window=2,
    )

    assert result["baseline"]["mean"] == pytest.approx(113.333)
    assert result["recent"]["latest_value"] == 150

    reversed_result = analyze_longitudinal_health(
        list(reversed(readings)),
        baseline_window=3,
        recent_window=2,
    )

    assert result == reversed_result