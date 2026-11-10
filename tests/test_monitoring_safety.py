import copy

import pytest

from healthguard.agents.monitoring_agent import (
    evaluate_health_monitoring,
)

from healthguard.agents.monitoring_safety import (
    MonitoringSafetyError,
    validate_monitoring_decision,
)


def make_analysis(
    status="within_configured_threshold",
    is_anomaly=False,
    z_score=0.5,
    baseline_std=5.0,
):
    return {
        "baseline": {
            "mean": 100.0,
            "standard_deviation": baseline_std,
        },
        "recent": {
            "mean": 105.0,
            "latest_value": 102.5,
        },
        "comparison": {
            "absolute_change": 5.0,
            "direction": "increasing",
        },
        "anomaly": {
            "status": status,
            "is_anomaly": is_anomaly,
            "z_score": z_score,
            "threshold": 2.0,
        },
    }


def make_decision():
    return evaluate_health_monitoring(
        "blood_glucose",
        "mg/dL",
        make_analysis(),
    )


def test_valid_decision_passes():
    result = validate_monitoring_decision(make_decision())

    assert result["safe"] is True
    assert result["validation_status"] == "passed"


def test_valid_anomaly_decision_passes():
    analysis = make_analysis(
        status="statistical_deviation_detected",
        is_anomaly=True,
        z_score=3.0,
    )

    decision = evaluate_health_monitoring(
        "heart_rate",
        "bpm",
        analysis,
    )

    result = validate_monitoring_decision(decision)

    assert result["safe"] is True
    assert result["monitoring_priority"] == "review_recommended"


def test_valid_zero_variance_decision_passes():
    analysis = make_analysis(
        status="insufficient_baseline_variability",
        is_anomaly=None,
        z_score=None,
        baseline_std=0.0,
    )

    decision = evaluate_health_monitoring(
        "weight",
        "kg",
        analysis,
    )

    result = validate_monitoring_decision(decision)

    assert result["safe"] is True
    assert result["monitoring_priority"] == "more_data_needed"


def test_invalid_input_type():
    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision([])


def test_invalid_priority():
    decision = make_decision()
    decision["monitoring_priority"] = "critical"

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_priority_status_mismatch():
    decision = make_decision()
    decision["monitoring_priority"] = "review_recommended"

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_invalid_direction():
    decision = make_decision()
    decision["observed_direction"] = "dangerous"

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_missing_evidence():
    decision = make_decision()
    del decision["evidence"]

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_nonfinite_evidence():
    decision = make_decision()
    decision["evidence"]["recent_mean"] = float("nan")

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_negative_standard_deviation():
    decision = make_decision()
    decision["evidence"]["baseline_standard_deviation"] = -1

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_invalid_threshold():
    decision = make_decision()
    decision["evidence"]["configured_threshold"] = 0

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_inconsistent_absolute_change():
    decision = make_decision()
    decision["evidence"]["absolute_change"] = 100

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_inconsistent_direction():
    decision = make_decision()
    decision["observed_direction"] = "decreasing"

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_inconsistent_z_score():
    decision = make_decision()
    decision["evidence"]["z_score"] = 5.0

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_missing_disclaimer():
    decision = make_decision()
    decision["disclaimer"] = "Everything is fine."

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_unsafe_diagnosis():
    decision = make_decision()
    decision["summary"] = "You have diabetes."

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_unsafe_medication_instruction():
    decision = make_decision()
    decision["recommended_actions"] = [
        "Stop taking your medication."
    ]

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_unsafe_safety_claim():
    decision = make_decision()
    decision["summary"] = "You are medically safe."

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_empty_recommended_actions():
    decision = make_decision()
    decision["recommended_actions"] = []

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_invalid_action_type():
    decision = make_decision()
    decision["recommended_actions"] = [123]

    with pytest.raises(MonitoringSafetyError):
        validate_monitoring_decision(decision)


def test_original_decision_not_modified():
    decision = make_decision()
    original = copy.deepcopy(decision)

    validate_monitoring_decision(decision)

    assert decision == original


def test_all_safety_checks_present():
    result = validate_monitoring_decision(make_decision())

    assert set(result["checks"]) == {
        "structure",
        "priority_consistency",
        "statistical_consistency",
        "language_screening",
        "disclaimer",
    }

    assert all(
        status == "passed"
        for status in result["checks"].values()
    )