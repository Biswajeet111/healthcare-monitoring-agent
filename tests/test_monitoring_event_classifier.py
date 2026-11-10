from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from healthguard.agents.monitoring_orchestrator import (
    run_monitoring_pipeline,
)

from healthguard.agents.monitoring_event_classifier import (
    classify_monitoring_event,
    MonitoringEventClassificationError,
)


def make_readings(values):
    start = datetime(
        2026, 11, 1, 10, 0,
        tzinfo=timezone.utc,
    )

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


def make_report(values=None):
    if values is None:
        values = [
            100, 102, 101, 103,
            104, 115, 120, 125,
        ]

    return run_monitoring_pipeline(
        metric_type="blood_glucose",
        unit="mg/dL",
        readings=make_readings(values),
    )


# ============================================================
# VALID CLASSIFICATION
# ============================================================

def test_statistical_deviation_classification():
    report = make_report()

    event = classify_monitoring_event(report)

    assert event["event_type"] == "statistical_deviation"
    assert event["event_level"] == "review"
    assert event["classification_status"] == "completed"


def test_routine_monitoring_classification():
    report = make_report(
        [100, 105, 102, 103, 101, 102, 103, 104]
    )

    event = classify_monitoring_event(report)

    assert event["event_type"] == "routine_monitoring"
    assert event["event_level"] == "routine"


def test_insufficient_variability_classification():
    report = make_report(
        [100, 100, 100, 100, 100, 110, 120, 130]
    )

    event = classify_monitoring_event(report)

    assert (
        event["event_type"]
        == "insufficient_baseline_variability"
    )

    assert event["event_level"] == "informational"
    assert event["evidence"]["z_score"] is None


def test_event_contains_metric_metadata():
    event = classify_monitoring_event(make_report())

    assert event["metric_type"] == "blood_glucose"
    assert event["unit"] == "mg/dL"


def test_event_contains_statistical_evidence():
    event = classify_monitoring_event(make_report())

    evidence = event["evidence"]

    assert "baseline_mean" in evidence
    assert "recent_mean" in evidence
    assert "latest_value" in evidence
    assert "z_score" in evidence
    assert "configured_threshold" in evidence


def test_event_timestamp_is_utc():
    event = classify_monitoring_event(make_report())

    timestamp = datetime.fromisoformat(event["created_at"])

    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() == timedelta(0)


def test_event_contains_disclaimer():
    event = classify_monitoring_event(make_report())

    assert "not medical urgency" in event["disclaimer"]
    assert "does not diagnose" in event["disclaimer"]


def test_event_does_not_contain_raw_readings():
    event = classify_monitoring_event(make_report())

    assert "readings" not in event
    assert "longitudinal_analysis" not in event


def test_report_not_modified():
    report = make_report()
    original = deepcopy(report)

    classify_monitoring_event(report)

    assert report == original


# ============================================================
# INVALID REPORTS
# ============================================================

def test_invalid_report_type():
    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(None)


def test_incomplete_pipeline():
    report = make_report()
    report["pipeline_status"] = "failed"

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_missing_monitoring_decision():
    report = make_report()
    del report["monitoring_decision"]

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_invalid_priority():
    report = make_report()

    report["monitoring_decision"][
        "monitoring_priority"
    ] = "critical"

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_priority_status_mismatch():
    report = make_report()

    report["monitoring_decision"][
        "monitoring_priority"
    ] = "routine_tracking"

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_failed_safety_validation():
    report = make_report()

    report["safety_validation"]["safe"] = False

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_missing_safety_checks():
    report = make_report()

    report["safety_validation"]["checks"] = {}

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_failed_individual_safety_check():
    report = make_report()

    report["safety_validation"]["checks"][
        "language_screening"
    ] = "failed"

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_metric_mismatch():
    report = make_report()

    report["monitoring_decision"]["metric_type"] = "heart_rate"

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_unit_mismatch():
    report = make_report()

    report["safety_validation"]["unit"] = "bpm"

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_nonfinite_evidence():
    report = make_report()

    report["monitoring_decision"]["evidence"][
        "baseline_mean"
    ] = float("nan")

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_invalid_threshold():
    report = make_report()

    report["monitoring_decision"]["evidence"][
        "configured_threshold"
    ] = -1

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_missing_required_z_score():
    report = make_report()

    report["monitoring_decision"]["evidence"][
        "z_score"
    ] = None

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_invalid_zero_variance_z_score():
    report = make_report(
        [100, 100, 100, 100, 100, 110, 120, 130]
    )

    report["monitoring_decision"]["evidence"][
        "z_score"
    ] = 3.5

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)


def test_missing_metric_type():
    report = make_report()

    del report["metric_type"]

    with pytest.raises(MonitoringEventClassificationError):
        classify_monitoring_event(report)