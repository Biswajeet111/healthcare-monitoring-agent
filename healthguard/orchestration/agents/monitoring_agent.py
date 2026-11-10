"""
Monitoring Agent — Phase 8

Analyzes recent health measurements, detects statistical deviations,
evaluates rule-based monitoring states, and flags urgent physiological conditions.
"""

import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.database.models import HealthMetric
from healthguard.agents.monitoring_orchestrator import (
    run_monitoring_pipeline,
    SUPPORTED_METRIC_TYPES,
)
from healthguard.orchestration.schemas import MonitoringAgentResult

logger = logging.getLogger(__name__)

# Urgent safety thresholds for physiological metrics (Workflow D)
CRITICAL_THRESHOLDS = {
    "blood_pressure_systolic": {
        "high": (180.0, "Systolic blood pressure is critically elevated (>= 180 mmHg). Potential hypertensive crisis."),
        "low": (70.0, "Systolic blood pressure is dangerously low (< 70 mmHg). Potential severe hypotension."),
    },
    "blood_pressure_diastolic": {
        "high": (120.0, "Diastolic blood pressure is critically elevated (>= 120 mmHg). Potential hypertensive crisis."),
        "low": (40.0, "Diastolic blood pressure is dangerously low (< 40 mmHg)."),
    },
    "blood_glucose": {
        "high": (300.0, "Blood glucose is critically elevated (> 300 mg/dL). Potential severe hyperglycemia."),
        "low": (54.0, "Blood glucose is critically low (< 54 mg/dL). Potential severe hypoglycemia."),
    },
    "heart_rate": {
        "high": (140.0, "Resting heart rate is critically elevated (> 140 bpm). Potential severe tachycardia."),
        "low": (40.0, "Resting heart rate is dangerously low (< 40 bpm). Potential severe bradycardia."),
    },
}


class MonitoringAgent:
    """Agent responsible for health metric monitoring and urgent condition detection."""

    def __init__(self, db: Session):
        self.db = db

    def analyze_metrics(
        self,
        user_id: int,
        metric_type: str = "blood_glucose",
        baseline_window: int = 5,
        recent_window: int = 3,
    ) -> MonitoringAgentResult:
        """
        Evaluate recent measurements for a user and metric type.
        """
        if metric_type not in SUPPORTED_METRIC_TYPES:
            return MonitoringAgentResult(
                status="insufficient_data",
                metric_type=metric_type,
                unit="unknown",
                summary=f"Unsupported metric type: {metric_type}",
            )

        # Retrieve recent readings for user
        statement = (
            select(HealthMetric)
            .where(
                HealthMetric.user_id == user_id,
                HealthMetric.metric_type == metric_type,
            )
            .order_by(
                HealthMetric.recorded_at.desc(),
                HealthMetric.id.desc(),
            )
            .limit(baseline_window + recent_window)
        )
        records = list(self.db.scalars(statement).all())

        if not records:
            return MonitoringAgentResult(
                status="insufficient_data",
                metric_type=metric_type,
                unit="unknown",
                summary=f"No recent measurements recorded for {metric_type.replace('_', ' ')}.",
            )

        records.reverse()  # chronological order
        unit = records[-1].unit
        latest_val = records[-1].value
        readings = [
            {
                "id": r.id,
                "value": r.value,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else "",
            }
            for r in records
        ]

        # 1. Check for immediate critical physiological thresholds (Workflow D)
        is_urgent = False
        urgent_reason: Optional[str] = None
        if metric_type in CRITICAL_THRESHOLDS:
            thresholds = CRITICAL_THRESHOLDS[metric_type]
            if "high" in thresholds and latest_val >= thresholds["high"][0]:
                is_urgent = True
                urgent_reason = thresholds["high"][1]
            elif "low" in thresholds and latest_val <= thresholds["low"][0]:
                is_urgent = True
                urgent_reason = thresholds["low"][1]

        # 2. If insufficient readings for full pipeline, return baseline observation
        required = baseline_window + recent_window
        if len(readings) < required:
            summary = (
                f"Latest {metric_type.replace('_', ' ')} is {latest_val} {unit}. "
                f"({len(readings)}/{required} readings available for full statistical baseline)."
            )
            if is_urgent:
                summary = f"URGENT: {urgent_reason} {summary}"

            return MonitoringAgentResult(
                status="urgent_review" if is_urgent else "insufficient_data",
                metric_type=metric_type,
                latest_value=latest_val,
                unit=unit,
                summary=summary,
                statistical_status="insufficient_baseline_data",
                is_urgent=is_urgent,
                urgent_reason=urgent_reason,
                monitoring_priority="urgent" if is_urgent else "routine",
                recent_readings_count=len(readings),
            )

        # 3. Run deterministic monitoring pipeline
        try:
            report = run_monitoring_pipeline(
                metric_type=metric_type,
                unit=unit,
                readings=readings,
                baseline_window=baseline_window,
                recent_window=recent_window,
            )
            decision = report.get("decision", {})
            statistical_status = decision.get("statistical_status", "routine_monitoring")
            monitoring_priority = decision.get("monitoring_priority", "routine")
            has_deviation = decision.get("statistical_deviation", False)

            status = "deviation" if has_deviation else "normal"
            if is_urgent:
                status = "urgent_review"
                monitoring_priority = "urgent"

            summary = (
                f"Latest {metric_type.replace('_', ' ')} is {latest_val} {unit}. "
                f"Statistical status: {statistical_status}. Monitoring priority: {monitoring_priority}."
            )
            if is_urgent:
                summary = f"URGENT ALERT: {urgent_reason} {summary}"

            return MonitoringAgentResult(
                status=status,
                metric_type=metric_type,
                latest_value=latest_val,
                unit=unit,
                summary=summary,
                statistical_status=statistical_status,
                is_urgent=is_urgent,
                urgent_reason=urgent_reason,
                monitoring_priority=monitoring_priority,
                recent_readings_count=len(readings),
            )
        except Exception as exc:
            logger.warning("Monitoring pipeline failed gracefully: %s", exc)
            return MonitoringAgentResult(
                status="urgent_review" if is_urgent else "normal",
                metric_type=metric_type,
                latest_value=latest_val,
                unit=unit,
                summary=f"Latest value is {latest_val} {unit}. Full statistical pipeline was not completed.",
                statistical_status="routine_monitoring",
                is_urgent=is_urgent,
                urgent_reason=urgent_reason,
                monitoring_priority="urgent" if is_urgent else "routine",
                recent_readings_count=len(readings),
            )
