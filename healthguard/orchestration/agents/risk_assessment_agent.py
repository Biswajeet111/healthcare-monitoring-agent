"""
Risk Assessment Agent — Phase 8

Integrates deterministic trend analytics and experimental ML screening estimates.
Strictly separates validated rule-based findings from experimental ML outputs.
Never presents experimental estimates as medical diagnoses.
"""

import logging
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.database.models import HealthMetric
from healthguard.analytics.trend_analyzer import analyze_health_trend
from healthguard.ml.diabetes_v3_predictor import (
    predict_diabetes_v3,
    DiabetesInputError,
    DiabetesModelError,
)
from healthguard.orchestration.schemas import (
    RiskAssessmentAgentResult,
    RiskLevel,
)

logger = logging.getLogger(__name__)


class RiskAssessmentAgent:
    """Agent responsible for deterministic risk analysis and experimental screening."""

    def __init__(self, db: Session):
        self.db = db

    def evaluate_risk(
        self,
        user_id: int,
        metric_type: str = "blood_glucose",
        experimental_ml: bool = False,
        ml_features: Optional[dict[str, Any]] = None,
    ) -> RiskAssessmentAgentResult:
        """
        Evaluate health risk using deterministic analytics and optional experimental ML.
        """
        rule_based_findings: list[dict[str, Any]] = []
        experimental_ml_estimates: list[dict[str, Any]] = []

        # 1. Deterministic Trend Analysis
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
            .limit(30)
        )
        records = list(self.db.scalars(statement).all())

        risk_level = RiskLevel.LOW
        if len(records) >= 2:
            readings = [
                {
                    "value": r.value,
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else "",
                }
                for r in records
            ]
            try:
                trend = analyze_health_trend(readings)
                direction = trend.get("direction", "unchanged")
                mean_val = trend.get("mean", 0.0)
                latest_val = readings[0]["value"]
                unit = records[0].unit

                rule_finding = {
                    "source": "deterministic_trend_analysis",
                    "metric_type": metric_type,
                    "direction": direction,
                    "mean": mean_val,
                    "latest": latest_val,
                    "unit": unit,
                    "sample_size": len(readings),
                    "interpretation": (
                        f"{metric_type.replace('_', ' ').title()} exhibits an "
                        f"{direction} trend with a 30-reading mean of {mean_val:.1f} {unit}."
                    ),
                }

                # Evaluate deterministic risk thresholds
                if metric_type == "blood_glucose":
                    if mean_val >= 180 or latest_val >= 200:
                        risk_level = RiskLevel.HIGH
                        rule_finding["clinical_relevance"] = "Consistently elevated glucose levels."
                    elif mean_val >= 126 or latest_val >= 140:
                        risk_level = RiskLevel.MODERATE
                        rule_finding["clinical_relevance"] = "Mildly elevated glucose levels."
                    elif latest_val < 70:
                        risk_level = RiskLevel.HIGH
                        rule_finding["clinical_relevance"] = "Hypoglycemic range reading."
                elif metric_type == "blood_pressure_systolic":
                    if mean_val >= 140 or latest_val >= 140:
                        risk_level = RiskLevel.HIGH
                        rule_finding["clinical_relevance"] = "Elevated systolic pressure trend."
                    elif mean_val >= 130 or latest_val >= 130:
                        risk_level = RiskLevel.MODERATE
                        rule_finding["clinical_relevance"] = "Prehypertension range reading."

                rule_based_findings.append(rule_finding)
            except Exception as exc:
                logger.warning("Deterministic trend analysis skipped: %s", exc)

        # 2. Experimental ML Screening (if requested or features provided)
        is_experimental_active = False
        if experimental_ml and ml_features:
            is_experimental_active = True
            try:
                ml_res = predict_diabetes_v3(ml_features)
                experimental_ml_estimates.append({
                    "model_name": ml_res.get("model", "LogisticRegression"),
                    "model_version": ml_res.get("model_version", "experimental-v3-candidate"),
                    "screening_result": ml_res.get("screening_result"),
                    "model_score": ml_res.get("model_score"),
                    "decision_threshold": ml_res.get("threshold"),
                    "is_medical_diagnosis": False,
                    "features_used": list(ml_features.keys()),
                    "disclaimer": ml_res.get("disclaimer"),
                })
            except (DiabetesInputError, DiabetesModelError, Exception) as exc:
                logger.info("Experimental ML model execution note: %s", exc)
                experimental_ml_estimates.append({
                    "status": "not_computable",
                    "reason": str(exc),
                    "disclaimer": (
                        "Experimental ML screening requires complete valid clinical parameters "
                        "and does not replace medical screening."
                    ),
                })

        # 3. Formulate structured summary
        summary_parts = []
        if rule_based_findings:
            summary_parts.append(f"Deterministic risk assessed as {risk_level.value.upper()}.")
            for f in rule_based_findings:
                summary_parts.append(f.get("interpretation", ""))
        else:
            summary_parts.append("Insufficient readings for longitudinal risk determination.")

        if experimental_ml_estimates:
            summary_parts.append(
                "NOTE: Includes experimental ML screening estimates (non-diagnostic research demonstration)."
            )

        return RiskAssessmentAgentResult(
            risk_level=risk_level,
            rule_based_findings=rule_based_findings,
            experimental_ml_estimates=experimental_ml_estimates,
            summary=" ".join(summary_parts),
            is_experimental=is_experimental_active,
        )
