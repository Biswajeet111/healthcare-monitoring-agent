import math
from datetime import datetime, timezone
from typing import Any


class MonitoringEventClassificationError(ValueError):
    """Raised when a monitoring report cannot be classified safely."""


EVENT_CLASSIFICATION_RULES = {
    "review_recommended": {
        "event_type": "statistical_deviation",
        "event_level": "review",
        "expected_status": "statistical_deviation_detected",
    },
    "more_data_needed": {
        "event_type": "insufficient_baseline_variability",
        "event_level": "informational",
        "expected_status": "insufficient_baseline_variability",
    },
    "routine_tracking": {
        "event_type": "routine_monitoring",
        "event_level": "routine",
        "expected_status": "within_configured_threshold",
    },
}


EVENT_MESSAGES = {
    "statistical_deviation": (
        "A statistical deviation was detected relative to "
        "the configured baseline. Review the recorded measurements "
        "and their data quality."
    ),
    "insufficient_baseline_variability": (
        "The baseline measurements have insufficient variability "
        "for the configured statistical deviation calculation. "
        "Continue recording measurements consistently."
    ),
    "routine_monitoring": (
        "The latest measurements remain within the configured "
        "statistical deviation threshold. Continue routine "
        "data tracking."
    ),
}


def _required_dict(parent: dict, key: str) -> dict:
    value = parent.get(key)

    if not isinstance(value, dict):
        raise MonitoringEventClassificationError(
            f"Missing or invalid section: {key}"
        )

    return value


def _required_text(parent: dict, key: str) -> str:
    value = parent.get(key)

    if not isinstance(value, str) or not value.strip():
        raise MonitoringEventClassificationError(
            f"{key} must be a non-empty string."
        )

    return value.strip()


def _finite_number(value: Any, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise MonitoringEventClassificationError(
            f"{field} must be a finite number."
        )

    try:
        if not math.isfinite(value):
            raise MonitoringEventClassificationError(
                f"{field} must be a finite number."
            )

        return float(value)

    except (TypeError, ValueError, OverflowError) as exc:
        raise MonitoringEventClassificationError(
            f"{field} must be a finite number."
        ) from exc


def classify_monitoring_event(
    monitoring_report: dict[str, Any],
) -> dict[str, Any]:
    """
    Classify a completed, safety-validated monitoring report.

    The classifier:
    - Rejects incomplete or unsafe reports.
    - Maps monitoring priorities to deterministic event types.
    - Preserves statistical evidence.
    - Generates non-diagnostic monitoring event messages.

    Event levels indicate data-review attention only.
    They do not represent clinical urgency.
    """

    # --------------------------------------------------------
    # 1. Validate top-level report
    # --------------------------------------------------------

    if not isinstance(monitoring_report, dict):
        raise MonitoringEventClassificationError(
            "Monitoring report must be a dictionary."
        )

    if monitoring_report.get("pipeline_status") != "completed":
        raise MonitoringEventClassificationError(
            "Monitoring pipeline has not completed."
        )

    metric_type = _required_text(
        monitoring_report,
        "metric_type",
    )

    unit = _required_text(
        monitoring_report,
        "unit",
    )

    # --------------------------------------------------------
    # 2. Validate monitoring decision
    # --------------------------------------------------------

    decision = _required_dict(
        monitoring_report,
        "monitoring_decision",
    )

    priority = _required_text(
        decision,
        "monitoring_priority",
    )

    statistical_status = _required_text(
        decision,
        "statistical_status",
    )

    if priority not in EVENT_CLASSIFICATION_RULES:
        raise MonitoringEventClassificationError(
            "Unsupported monitoring priority."
        )

    rule = EVENT_CLASSIFICATION_RULES[priority]

    if statistical_status != rule["expected_status"]:
        raise MonitoringEventClassificationError(
            "Monitoring priority contradicts statistical status."
        )

    if _required_text(decision, "metric_type") != metric_type:
        raise MonitoringEventClassificationError(
            "Decision metric type does not match the report."
        )

    if _required_text(decision, "unit") != unit:
        raise MonitoringEventClassificationError(
            "Decision unit does not match the report."
        )

    # --------------------------------------------------------
    # 3. Validate safety report
    # --------------------------------------------------------

    safety = _required_dict(
        monitoring_report,
        "safety_validation",
    )

    if safety.get("safe") is not True:
        raise MonitoringEventClassificationError(
            "Monitoring report has not passed safety validation."
        )

    if safety.get("validation_status") != "passed":
        raise MonitoringEventClassificationError(
            "Safety validation status is not passed."
        )

    if _required_text(safety, "metric_type") != metric_type:
        raise MonitoringEventClassificationError(
            "Safety metric type does not match the report."
        )

    if _required_text(safety, "unit") != unit:
        raise MonitoringEventClassificationError(
            "Safety unit does not match the report."
        )

    if (
        _required_text(safety, "monitoring_priority")
        != priority
    ):
        raise MonitoringEventClassificationError(
            "Safety priority does not match the decision."
        )

    if (
        _required_text(safety, "statistical_status")
        != statistical_status
    ):
        raise MonitoringEventClassificationError(
            "Safety status does not match the decision."
        )

    checks = _required_dict(safety, "checks")

    required_checks = {
        "structure",
        "priority_consistency",
        "statistical_consistency",
        "language_screening",
        "disclaimer",
    }

    if not required_checks.issubset(checks):
        raise MonitoringEventClassificationError(
            "Required safety checks are missing."
        )

    if any(
        checks[check] != "passed"
        for check in required_checks
    ):
        raise MonitoringEventClassificationError(
            "One or more safety checks have not passed."
        )

    # --------------------------------------------------------
    # 4. Validate statistical evidence
    # --------------------------------------------------------

    evidence = _required_dict(
        decision,
        "evidence",
    )

    baseline_mean = _finite_number(
        evidence.get("baseline_mean"),
        "baseline_mean",
    )

    recent_mean = _finite_number(
        evidence.get("recent_mean"),
        "recent_mean",
    )

    latest_value = _finite_number(
        evidence.get("latest_value"),
        "latest_value",
    )

    threshold = _finite_number(
        evidence.get("configured_threshold"),
        "configured_threshold",
    )

    if threshold <= 0:
        raise MonitoringEventClassificationError(
            "Configured threshold must be positive."
        )

    z_score = evidence.get("z_score")

    if z_score is not None:
        z_score = _finite_number(
            z_score,
            "z_score",
        )

    if (
        statistical_status
        == "insufficient_baseline_variability"
        and z_score is not None
    ):
        raise MonitoringEventClassificationError(
            "Insufficient variability requires a null z-score."
        )

    if (
        statistical_status
        != "insufficient_baseline_variability"
        and z_score is None
    ):
        raise MonitoringEventClassificationError(
            "Statistical status requires a valid z-score."
        )

    # --------------------------------------------------------
    # 5. Generate event classification
    # --------------------------------------------------------

    event_type = rule["event_type"]
    event_level = rule["event_level"]

    event_message = EVENT_MESSAGES[event_type]

    return {
        "event_type": event_type,
        "event_level": event_level,
        "metric_type": metric_type,
        "unit": unit,
        "monitoring_priority": priority,
        "statistical_status": statistical_status,
        "message": event_message,
        "evidence": {
            "baseline_mean": baseline_mean,
            "recent_mean": recent_mean,
            "latest_value": latest_value,
            "z_score": z_score,
            "configured_threshold": threshold,
        },
        "source": "healthguard_monitoring_agent",
        "classification_status": "completed",
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "disclaimer": (
            "This event represents statistical data-review "
            "attention only, not medical urgency. It does not "
            "diagnose conditions, establish medical safety, "
            "or recommend treatment."
        ),
    }