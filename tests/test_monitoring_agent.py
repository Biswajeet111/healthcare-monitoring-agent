import pytest

from healthguard.agents.monitoring_agent import (
    evaluate_health_monitoring,
    MonitoringAgentError,
)


def make_analysis(
    status="within_configured_threshold",
    is_anomaly=False,
    z_score=0.5,
    direction="increasing",
):
    return {
        "baseline": {
            "mean": 100.0,
            "standard_deviation": 5.0,
        },
        "recent": {
            "mean": 105.0,
            "latest_value": 102.5,
        },
        "comparison": {
            "absolute_change": 5.0,
            "direction": direction,
        },
        "anomaly": {
            "status": status,
            "is_anomaly": is_anomaly,
            "z_score": z_score,
            "threshold": 2.0,
        },
    }


def test_routine_tracking():
    result = evaluate_health_monitoring(
        "blood_glucose",
        "mg/dL",
        make_analysis(),
    )

    assert result["monitoring_priority"] == "routine_tracking"
    assert result["statistical_status"] == "within_configured_threshold"
    assert result["observed_direction"] == "increasing"


def test_statistical_deviation():
    result = evaluate_health_monitoring(
        "heart_rate",
        "bpm",
        make_analysis(
            status="statistical_deviation_detected",
            is_anomaly=True,
            z_score=3.0,
        ),
    )

    assert result["monitoring_priority"] == "review_recommended"
    assert result["evidence"]["z_score"] == 3.0


def test_zero_variance_baseline():
    result = evaluate_health_monitoring(
        "weight",
        "kg",
        make_analysis(
            status="insufficient_baseline_variability",
            is_anomaly=None,
            z_score=None,
        ),
    )

    assert result["monitoring_priority"] == "more_data_needed"


def test_decreasing_direction():
    result = evaluate_health_monitoring(
        "weight",
        "kg",
        make_analysis(direction="decreasing"),
    )

    assert result["observed_direction"] == "decreasing"


def test_missing_analysis_section():
    analysis = make_analysis()
    del analysis["baseline"]

    with pytest.raises(MonitoringAgentError):
        evaluate_health_monitoring(
            "heart_rate", "bpm", analysis
        )


def test_invalid_direction():
    analysis = make_analysis(direction="dangerous")

    with pytest.raises(MonitoringAgentError):
        evaluate_health_monitoring(
            "heart_rate", "bpm", analysis
        )


def test_invalid_anomaly_status():
    analysis = make_analysis()
    analysis["anomaly"]["status"] = "critical"

    with pytest.raises(MonitoringAgentError):
        evaluate_health_monitoring(
            "heart_rate", "bpm", analysis
        )


def test_inconsistent_anomaly_flag():
    analysis = make_analysis(
        status="statistical_deviation_detected",
        is_anomaly=False,
        z_score=3.0,
    )

    with pytest.raises(MonitoringAgentError):
        evaluate_health_monitoring(
            "heart_rate", "bpm", analysis
        )


def test_non_finite_value():
    analysis = make_analysis()
    analysis["recent"]["latest_value"] = float("nan")

    with pytest.raises(MonitoringAgentError):
        evaluate_health_monitoring(
            "heart_rate", "bpm", analysis
        )


def test_invalid_threshold():
    analysis = make_analysis()
    analysis["anomaly"]["threshold"] = 0

    with pytest.raises(MonitoringAgentError):
        evaluate_health_monitoring(
            "heart_rate", "bpm", analysis
        )


def test_empty_metric_type():
    with pytest.raises(MonitoringAgentError):
        evaluate_health_monitoring(
            "", "bpm", make_analysis()
        )


def test_empty_unit():
    with pytest.raises(MonitoringAgentError):
        evaluate_health_monitoring(
            "heart_rate", "", make_analysis()
        )


def test_disclaimer_present():
    result = evaluate_health_monitoring(
        "heart_rate",
        "bpm",
        make_analysis(),
    )

    assert "not medical urgency" in result["disclaimer"]
    assert "does not establish medical safety" in result["disclaimer"]


def test_recommended_actions_present():
    result = evaluate_health_monitoring(
        "heart_rate",
        "bpm",
        make_analysis(),
    )

    assert isinstance(result["recommended_actions"], list)
    assert len(result["recommended_actions"]) >= 2