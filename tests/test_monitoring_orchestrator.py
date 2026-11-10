from datetime import datetime, timedelta, timezone

import pytest

from healthguard.agents.monitoring_orchestrator import (
    run_monitoring_pipeline,
    MonitoringOrchestrationError,
)


def make_readings(values):
    start = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)

    return [
        {
            "id": index + 1,
            "recorded_at": (
                start + timedelta(days=index)
            ).isoformat(),
            "value": value,
        }
        for index, value in enumerate(values)
    ]


def test_successful_pipeline():
    result = run_monitoring_pipeline(
        metric_type="blood_glucose",
        unit="mg/dL",
        readings=make_readings(
            [100, 102, 101, 103, 104, 115, 120, 125]
        ),
    )

    assert result["pipeline_status"] == "completed"
    assert result["metric_type"] == "blood_glucose"
    assert result["unit"] == "mg/dL"

    assert result["safety_validation"]["safe"] is True

    assert (
        result["monitoring_decision"]["monitoring_priority"]
        == "review_recommended"
    )


def test_routine_tracking_pipeline():
    result = run_monitoring_pipeline(
        metric_type="heart_rate",
        unit="bpm",
        readings=make_readings(
            [70, 75, 72, 73, 71, 72, 73, 74]
        ),
    )

    assert result["pipeline_status"] == "completed"

    assert (
        result["monitoring_decision"]["monitoring_priority"]
        == "routine_tracking"
    )


def test_zero_variance_pipeline():
    result = run_monitoring_pipeline(
        metric_type="weight",
        unit="kg",
        readings=make_readings(
            [70, 70, 70, 70, 70, 71, 72, 73]
        ),
    )

    assert result["pipeline_status"] == "completed"

    assert (
        result["monitoring_decision"]["monitoring_priority"]
        == "more_data_needed"
    )


def test_decreasing_measurements():
    result = run_monitoring_pipeline(
        metric_type="weight",
        unit="kg",
        readings=make_readings(
            [80, 79, 78, 77, 76, 75, 74, 73]
        ),
    )

    assert (
        result["monitoring_decision"]["observed_direction"]
        == "decreasing"
    )


def test_unchanged_measurements():
    result = run_monitoring_pipeline(
        metric_type="steps",
        unit="count",
        readings=make_readings(
            [1000, 1100, 900, 1000, 1000, 1000, 1000, 1000]
        ),
    )

    assert (
        result["monitoring_decision"]["observed_direction"]
        == "unchanged"
    )


def test_insufficient_readings():
    with pytest.raises(MonitoringOrchestrationError):
        run_monitoring_pipeline(
            metric_type="blood_glucose",
            unit="mg/dL",
            readings=make_readings([100, 105, 110]),
        )


def test_invalid_metric_type():
    with pytest.raises(MonitoringOrchestrationError):
        run_monitoring_pipeline(
            metric_type="temperature",
            unit="C",
            readings=make_readings([36.5] * 8),
        )


def test_empty_unit():
    with pytest.raises(MonitoringOrchestrationError):
        run_monitoring_pipeline(
            metric_type="heart_rate",
            unit="",
            readings=make_readings([70] * 8),
        )


def test_invalid_baseline_window():
    with pytest.raises(MonitoringOrchestrationError):
        run_monitoring_pipeline(
            metric_type="heart_rate",
            unit="bpm",
            readings=make_readings([70] * 8),
            baseline_window=1,
        )


def test_invalid_recent_window():
    with pytest.raises(MonitoringOrchestrationError):
        run_monitoring_pipeline(
            metric_type="heart_rate",
            unit="bpm",
            readings=make_readings([70] * 8),
            recent_window=0,
        )


def test_invalid_anomaly_threshold():
    with pytest.raises(MonitoringOrchestrationError):
        run_monitoring_pipeline(
            metric_type="heart_rate",
            unit="bpm",
            readings=make_readings([70] * 8),
            anomaly_threshold=-1,
        )


def test_nonfinite_measurement():
    readings = make_readings([70] * 8)
    readings[3]["value"] = float("nan")

    with pytest.raises(MonitoringOrchestrationError):
        run_monitoring_pipeline(
            metric_type="heart_rate",
            unit="bpm",
            readings=readings,
        )


def test_unsorted_measurements():
    readings = make_readings(
        [100, 102, 101, 103, 104, 115, 120, 125]
    )

    result = run_monitoring_pipeline(
        metric_type="blood_glucose",
        unit="mg/dL",
        readings=list(reversed(readings)),
    )

    assert result["pipeline_status"] == "completed"

    assert result["longitudinal_analysis"]["recent"][
        "latest_value"
    ] == 125


def test_custom_analysis_windows():
    result = run_monitoring_pipeline(
        metric_type="blood_glucose",
        unit="mg/dL",
        readings=make_readings(
            [100, 101, 102, 103, 104, 105]
        ),
        baseline_window=3,
        recent_window=2,
    )

    assert result["pipeline_status"] == "completed"

    assert result["longitudinal_analysis"]["baseline"][
        "count"
    ] == 3

    assert result["longitudinal_analysis"]["recent"][
        "count"
    ] == 2


def test_safety_validation_report():
    result = run_monitoring_pipeline(
        metric_type="heart_rate",
        unit="bpm",
        readings=make_readings(
            [70, 75, 72, 73, 71, 72, 73, 74]
        ),
    )

    safety = result["safety_validation"]

    assert safety["safe"] is True
    assert safety["validation_status"] == "passed"

    assert all(
        status == "passed"
        for status in safety["checks"].values()
    )


def test_disclaimer_present():
    result = run_monitoring_pipeline(
        metric_type="heart_rate",
        unit="bpm",
        readings=make_readings(
            [70, 75, 72, 73, 71, 72, 73, 74]
        ),
    )

    assert "not clinical urgency" in result["disclaimer"]
    assert "do not establish medical safety" in result["disclaimer"]


def test_pipeline_does_not_modify_readings():
    readings = make_readings(
        [70, 75, 72, 73, 71, 72, 73, 74]
    )

    original = [dict(reading) for reading in readings]

    run_monitoring_pipeline(
        metric_type="heart_rate",
        unit="bpm",
        readings=readings,
    )

    assert readings == original