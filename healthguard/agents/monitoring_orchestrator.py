from typing import Any

from healthguard.analytics.longitudinal_analyzer import (
    analyze_longitudinal_health,
    LongitudinalAnalysisError,
)

from healthguard.agents.monitoring_agent import (
    evaluate_health_monitoring,
    MonitoringAgentError,
)

from healthguard.agents.monitoring_safety import (
    validate_monitoring_decision,
    MonitoringSafetyError,
)


class MonitoringOrchestrationError(ValueError):
    """Raised when the monitoring pipeline cannot complete safely."""


SUPPORTED_METRIC_TYPES = {
    "blood_pressure_systolic",
    "blood_pressure_diastolic",
    "blood_glucose",
    "heart_rate",
    "weight",
    "height",
    "steps",
    "sleep_duration",
}


def run_monitoring_pipeline(
    metric_type: str,
    unit: str,
    readings: list[dict[str, Any]],
    baseline_window: int = 5,
    recent_window: int = 3,
    anomaly_threshold: float = 2.0,
) -> dict[str, Any]:
    """
    Execute the deterministic HealthGuard monitoring pipeline.

    Pipeline:
        1. Validate metric metadata
        2. Analyze longitudinal measurements
        3. Generate monitoring decision
        4. Validate decision through safety layer
        5. Return structured monitoring report

    Monitoring priority represents statistical data-review
    attention, not medical urgency.

    No external APIs, LLMs, or database writes are performed.
    """

    if (
        not isinstance(metric_type, str)
        or metric_type not in SUPPORTED_METRIC_TYPES
    ):
        raise MonitoringOrchestrationError(
            "Unsupported health metric type."
        )

    if not isinstance(unit, str) or not unit.strip():
        raise MonitoringOrchestrationError(
            "Measurement unit must be a non-empty string."
        )

    try:
        # ----------------------------------------------------
        # STAGE 1: LONGITUDINAL ANALYSIS
        # ----------------------------------------------------

        longitudinal_analysis = analyze_longitudinal_health(
            readings=readings,
            baseline_window=baseline_window,
            recent_window=recent_window,
            anomaly_threshold=anomaly_threshold,
        )

        # ----------------------------------------------------
        # STAGE 2: MONITORING DECISION ENGINE
        # ----------------------------------------------------

        monitoring_decision = evaluate_health_monitoring(
            metric_type=metric_type,
            unit=unit,
            analysis=longitudinal_analysis,
        )

        # ----------------------------------------------------
        # STAGE 3: SAFETY VALIDATION
        # ----------------------------------------------------

        safety_report = validate_monitoring_decision(
            monitoring_decision
        )

        if safety_report.get("safe") is not True:
            raise MonitoringOrchestrationError(
                "Monitoring decision failed safety validation."
            )

        # ----------------------------------------------------
        # STAGE 4: STRUCTURED REPORT
        # ----------------------------------------------------

        return {
            "pipeline_status": "completed",
            "metric_type": metric_type,
            "unit": unit,
            "longitudinal_analysis": longitudinal_analysis,
            "monitoring_decision": monitoring_decision,
            "safety_validation": safety_report,
            "disclaimer": (
                "This report provides statistical monitoring "
                "information only. Monitoring priority is not "
                "clinical urgency. Statistical results do not "
                "establish medical safety, diagnose conditions, "
                "or recommend treatment."
            ),
        }

    except (
        LongitudinalAnalysisError,
        MonitoringAgentError,
        MonitoringSafetyError,
    ) as exc:
        raise MonitoringOrchestrationError(
            f"Monitoring pipeline failed: {exc}"
        ) from exc