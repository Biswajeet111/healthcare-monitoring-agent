import pytest

from healthguard.analytics.trend_analyzer import (
    analyze_health_trend,
    TrendAnalysisError,
)


def test_increasing_trend():

    readings = [
        {
            "recorded_at": "2026-11-01T10:00:00",
            "value": 105,
        },
        {
            "recorded_at": "2026-11-03T10:00:00",
            "value": 112,
        },
        {
            "recorded_at": "2026-11-05T10:00:00",
            "value": 119,
        },
        {
            "recorded_at": "2026-11-07T10:00:00",
            "value": 125,
        },
    ]

    result = analyze_health_trend(readings)

    assert result["count"] == 4
    assert result["first_value"] == 105
    assert result["latest_value"] == 125
    assert result["direction"] == "increasing"
    assert result["absolute_change"] == 20
    assert result["percentage_change"] == pytest.approx(
        19.048, abs=0.001
    )


def test_decreasing_trend():

    readings = [
        {
            "recorded_at": "2026-11-01T10:00:00",
            "value": 130,
        },
        {
            "recorded_at": "2026-11-05T10:00:00",
            "value": 115,
        },
    ]

    result = analyze_health_trend(readings)

    assert result["direction"] == "decreasing"
    assert result["absolute_change"] == -15


def test_unchanged_trend():

    readings = [
        {
            "recorded_at": "2026-11-01T10:00:00",
            "value": 100,
        },
        {
            "recorded_at": "2026-11-05T10:00:00",
            "value": 100,
        },
    ]

    result = analyze_health_trend(readings)

    assert result["direction"] == "unchanged"


def test_insufficient_readings():

    with pytest.raises(TrendAnalysisError):

        analyze_health_trend(
            [
                {
                    "recorded_at": "2026-11-01T10:00:00",
                    "value": 100,
                }
            ]
        )


def test_invalid_value():

    readings = [
        {
            "recorded_at": "2026-11-01T10:00:00",
            "value": "invalid",
        },
        {
            "recorded_at": "2026-11-02T10:00:00",
            "value": 110,
        },
    ]

    with pytest.raises(TrendAnalysisError):
        analyze_health_trend(readings)


def test_non_finite_value():

    readings = [
        {
            "recorded_at": "2026-11-01T10:00:00",
            "value": float("nan"),
        },
        {
            "recorded_at": "2026-11-02T10:00:00",
            "value": 110,
        },
    ]

    with pytest.raises(TrendAnalysisError):
        analyze_health_trend(readings)

def test_identical_timestamp_deterministic_order():

    readings_a = [
        {
            "recorded_at": "2026-11-10T10:00:00",
            "value": 120,
        },
        {
            "recorded_at": "2026-11-10T10:00:00",
            "value": 100,
        },
    ]

    readings_b = list(reversed(readings_a))

    result_a = analyze_health_trend(readings_a)
    result_b = analyze_health_trend(readings_b)

    assert result_a == result_b

    assert result_a["first_value"] == 100
    assert result_a["latest_value"] == 120
    assert result_a["absolute_change"] == 20
    assert result_a["direction"] == "increasing"