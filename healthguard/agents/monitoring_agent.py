from datetime import datetime, timezone
from typing import Any
import math


class MonitoringAgentError(ValueError):
    """Raised when monitoring input is invalid."""


SUPPORTED_DIRECTIONS = {
    "increasing",
    "decreasing",
    "unchanged",
}

SUPPORTED_ANOMALY_STATUSES = {
    "statistical_deviation_detected",
    "within_configured_threshold",
    "insufficient_baseline_variability",
}


def _validate_finite_number(value, field_name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise MonitoringAgentError(
            f"{field_name} must be a finite number."
        )

    return float(value)


def _validate_analysis(analysis):

    if not isinstance(analysis, dict):
        raise MonitoringAgentError(
            "Analysis must be a dictionary."
        )

    required_sections = [
        "baseline",
        "recent",
        "comparison",
        "anomaly",
    ]

    for section in required_sections:
        if not isinstance(analysis.get(section), dict):
            raise MonitoringAgentError(
                f"Missing or invalid section: {section}"
            )

    baseline = analysis["baseline"]
    recent = analysis["recent"]
    comparison = analysis["comparison"]
    anomaly = analysis["anomaly"]

    baseline_mean = _validate_finite_number(
        baseline.get("mean"),
        "baseline.mean",
    )

    baseline_std = _validate_finite_number(
        baseline.get("standard_deviation"),
        "baseline.standard_deviation",
    )

    recent_mean = _validate_finite_number(
        recent.get("mean"),
        "recent.mean",
    )

    latest_value = _validate_finite_number(
        recent.get("latest_value"),
        "recent.latest_value",
    )

    absolute_change = _validate_finite_number(
        comparison.get("absolute_change"),
        "comparison.absolute_change",
    )

    direction = comparison.get("direction")

    if direction not in SUPPORTED_DIRECTIONS:
        raise MonitoringAgentError(
            "Unsupported comparison direction."
        )

    anomaly_status = anomaly.get("status")

    if anomaly_status not in SUPPORTED_ANOMALY_STATUSES:
        raise MonitoringAgentError(
            "Unsupported anomaly status."
        )

    is_anomaly = anomaly.get("is_anomaly")

    if is_anomaly is not None and type(is_anomaly) is not bool:
        raise MonitoringAgentError(
            "anomaly.is_anomaly must be boolean or null."
        )

    z_score = anomaly.get("z_score")

    if z_score is not None:
        z_score = _validate_finite_number(
            z_score,
            "anomaly.z_score",
        )

    threshold = _validate_finite_number(
        anomaly.get("threshold"),
        "anomaly.threshold",
    )

    if threshold <= 0:
        raise MonitoringAgentError(
            "Anomaly threshold must be positive."
        )

    if baseline_std < 0:
        raise MonitoringAgentError(
            "Baseline standard deviation cannot be negative."
        )

    if anomaly_status == "statistical_deviation_detected":
        if (
            is_anomaly is not True
            or z_score is None
            or abs(z_score) < threshold - 0.001
        ):
            raise MonitoringAgentError(
                "Inconsistent anomaly detection result."
            )

    elif anomaly_status == "within_configured_threshold":
        if (
            is_anomaly is not False
            or z_score is None
            or abs(z_score) >= threshold + 0.001
        ):
            raise MonitoringAgentError(
                "Inconsistent normal-range statistical result."
            )

    else:
        if is_anomaly is not None or z_score is not None:
            raise MonitoringAgentError(
                "Zero-variance analysis must have null anomaly values."
            )

    return {
        "baseline_mean": baseline_mean,
        "baseline_std": baseline_std,
        "recent_mean": recent_mean,
        "latest_value": latest_value,
        "absolute_change": absolute_change,
        "direction": direction,
        "anomaly_status": anomaly_status,
        "is_anomaly": is_anomaly,
        "z_score": z_score,
        "threshold": threshold,
    }


def evaluate_health_monitoring(
    metric_type: str,
    unit: str,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate a longitudinal analysis and produce
    non-diagnostic monitoring recommendations.

    Priority describes data-review attention,
    not clinical urgency.
    """

    if not isinstance(metric_type, str) or not metric_type.strip():
        raise MonitoringAgentError(
            "metric_type must be a non-empty string."
        )

    if not isinstance(unit, str) or not unit.strip():
        raise MonitoringAgentError(
            "unit must be a non-empty string."
        )

    validated = _validate_analysis(analysis)

    status = validated["anomaly_status"]
    direction = validated["direction"]

    if status == "statistical_deviation_detected":

        priority = "review_recommended"

        summary = (
            "The latest recorded measurement differs "
            "from the historical statistical baseline "
            "beyond the configured threshold."
        )

        recommended_actions = [
            "Verify the measurement value, unit, and timestamp.",
            "Check whether the measurement was entered correctly.",
            "Review additional measurements for consistency.",
        ]

    elif status == "insufficient_baseline_variability":

        priority = "more_data_needed"

        summary = (
            "The historical baseline has no measurable "
            "variation, so a standard z-score cannot "
            "be calculated."
        )

        recommended_actions = [
            "Review the recorded measurement history.",
            "Collect additional measurements over time.",
            "Confirm that repeated values were recorded correctly.",
        ]

    else:

        priority = "routine_tracking"

        summary = (
            "The latest recorded measurement is within "
            "the configured statistical deviation threshold."
        )

        recommended_actions = [
            "Continue routine measurement tracking.",
            "Review changes across multiple observations.",
        ]

    return {
        "metric_type": metric_type,
        "unit": unit,
        "monitoring_priority": priority,
        "statistical_status": status,
        "observed_direction": direction,
        "summary": summary,
        "recommended_actions": recommended_actions,
        "evidence": {
            "baseline_mean": validated["baseline_mean"],
            "baseline_standard_deviation": validated["baseline_std"],
            "recent_mean": validated["recent_mean"],
            "latest_value": validated["latest_value"],
            "absolute_change": validated["absolute_change"],
            "z_score": validated["z_score"],
            "configured_threshold": validated["threshold"],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Monitoring priority reflects statistical data-review "
            "attention only, not medical urgency. A measurement "
            "within the configured threshold does not establish "
            "medical safety. This system does not diagnose, "
            "predict disease, or recommend treatment."
        ),
    }