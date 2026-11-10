"""
Central Agentic AI Orchestrator — Phase 8

Coordinates:
- Monitoring Agent
- Risk Assessment Agent
- Medication Agent
- Medical Knowledge Agent
- Notification Agent

Implements Workflows A, B, C, D with explicit states, audit logging,
idempotency, timeouts, graceful degradation, and medical safety controls.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.database.models import (
    AgentExecutionAudit,
    HealthMetric,
    MonitoringEvent,
    UserProfile,
)
from healthguard.orchestration.agents.monitoring_agent import MonitoringAgent
from healthguard.orchestration.agents.risk_assessment_agent import RiskAssessmentAgent
from healthguard.orchestration.agents.medication_agent import MedicationAgent
from healthguard.orchestration.agents.medical_knowledge_agent import MedicalKnowledgeAgent
from healthguard.orchestration.agents.notification_agent import NotificationAgent
from healthguard.orchestration.schemas import (
    ConsolidatedHealthSummaryResponse,
    ExecutionStepLog,
    MonitoringAgentResult,
    OrchestrationState,
    RiskAssessmentAgentResult,
    MedicationAgentResult,
    MedicalKnowledgeAgentResult,
    NotificationAgentResult,
    WorkflowType,
)
from healthguard.rag.safety import EMERGENCY_GUIDANCE
from healthguard.services.medication_reminder_service import generate_reminders_for_user

logger = logging.getLogger(__name__)


class AgenticOrchestrationError(Exception):
    """Raised when an unrecoverable agent orchestration error occurs."""


class AgenticOrchestrator:
    """Central orchestrator coordinating multi-agent workflows."""

    def __init__(self, db: Session):
        self.db = db
        self.monitoring_agent = MonitoringAgent(db)
        self.risk_agent = RiskAssessmentAgent(db)
        self.medication_agent = MedicationAgent(db)
        self.knowledge_agent = MedicalKnowledgeAgent(db)
        self.notification_agent = NotificationAgent(db)

    def _generate_idempotency_key(self, user_id: int, workflow_name: str, payload: dict) -> str:
        """Create a deterministic SHA-256 fingerprint for idempotency checks."""
        raw = f"{user_id}:{workflow_name}:{json.dumps(payload, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _check_idempotent_recent_execution(
        self,
        user_id: int,
        idempotency_key: str,
        cooldown_seconds: int = 30,
    ) -> Optional[AgentExecutionAudit]:
        """Check if an identical workflow executed successfully within cooldown."""
        cutoff = datetime.utcnow() - timedelta(seconds=cooldown_seconds)
        stmt = (
            select(AgentExecutionAudit)
            .where(
                AgentExecutionAudit.user_id == user_id,
                AgentExecutionAudit.idempotency_key == idempotency_key,
                AgentExecutionAudit.status.in_(["completed", "escalated", "degraded"]),
                AgentExecutionAudit.created_at >= cutoff,
            )
            .order_by(AgentExecutionAudit.created_at.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()

    def _record_audit(
        self,
        user_id: int,
        workflow_type: str,
        status: str,
        idempotency_key: Optional[str],
        input_payload: dict,
        execution_steps: list[ExecutionStepLog],
        result_summary: dict,
        duration_ms: int,
        error_message: Optional[str] = None,
    ) -> AgentExecutionAudit:
        """Persist execution audit trail into database."""
        audit = AgentExecutionAudit(
            user_id=user_id,
            workflow_type=workflow_type,
            status=status,
            idempotency_key=idempotency_key,
            input_payload=json.dumps(input_payload, default=str),
            execution_steps=json.dumps([s.model_dump() for s in execution_steps], default=str),
            result_summary=json.dumps(result_summary, default=str),
            error_message=error_message,
            duration_ms=duration_ms,
            created_at=datetime.utcnow() - timedelta(milliseconds=duration_ms),
            completed_at=datetime.utcnow(),
        )
        self.db.add(audit)
        try:
            self.db.commit()
            self.db.refresh(audit)
        except Exception as exc:
            self.db.rollback()
            logger.warning("Failed to commit agent audit log: %s", exc)
        return audit

    # ============================================================
    # WORKFLOW A — NEW HEALTH MEASUREMENT ASSESSMENT
    # ============================================================

    def run_workflow_a_measurement(
        self,
        user_id: int,
        metric_type: str = "blood_glucose",
        metric_id: Optional[int] = None,
        include_knowledge: bool = True,
        experimental_ml: bool = False,
        ml_features: Optional[dict[str, Any]] = None,
    ) -> ConsolidatedHealthSummaryResponse:
        """
        Workflow A:
        1. Run monitoring rules on recent readings.
        2. Evaluate relevant trends.
        3. Invoke risk assessment when appropriate.
        4. Check for safety escalation (Workflow D).
        5. Retrieve medical knowledge when useful.
        6. Generate safe, understandable summary.
        7. Deliver eligible notifications.
        """
        start_time = time.time()
        steps: list[ExecutionStepLog] = []
        state = OrchestrationState.IN_PROGRESS
        safety_escalation = None

        idempotency_key = self._generate_idempotency_key(
            user_id,
            WorkflowType.WORKFLOW_A_NEW_MEASUREMENT.value,
            {"metric_type": metric_type, "metric_id": metric_id},
        )

        recent_audit = self._check_idempotent_recent_execution(user_id, idempotency_key)
        if recent_audit and recent_audit.result_summary:
            try:
                cached_data = json.loads(recent_audit.result_summary)
                return ConsolidatedHealthSummaryResponse(**cached_data)
            except Exception:
                pass  # Recompute if deserialization fails

        # Step 1: Monitoring Agent
        step_t0 = time.time()
        monitoring_res = self.monitoring_agent.analyze_metrics(
            user_id=user_id,
            metric_type=metric_type,
        )
        steps.append(ExecutionStepLog(
            agent_name="MonitoringAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status=monitoring_res.status,
            details=monitoring_res.summary,
        ))

        # Check for Workflow D Escalation
        if monitoring_res.is_urgent:
            state = OrchestrationState.ESCALATED
            safety_escalation = {
                "level": "CRITICAL_PHYSIOLOGICAL_VALUE",
                "urgent_reason": monitoring_res.urgent_reason,
                "guidance": (
                    f"{EMERGENCY_GUIDANCE}\n\n"
                    f"Action Required: Your recorded measurement ({monitoring_res.latest_value} "
                    f"{monitoring_res.unit}) indicates a potentially critical physiological state. "
                    "Seek immediate professional medical evaluation or contact emergency medical services."
                ),
                "disclaimer": (
                    "HealthGuard AI is an automated monitoring aid, not an emergency service. "
                    "The system does not autonomously contact emergency dispatch or alter therapy."
                ),
            }

        # Step 2: Risk Assessment Agent
        step_t0 = time.time()
        risk_res = self.risk_agent.evaluate_risk(
            user_id=user_id,
            metric_type=metric_type,
            experimental_ml=experimental_ml,
            ml_features=ml_features,
        )
        steps.append(ExecutionStepLog(
            agent_name="RiskAssessmentAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status=risk_res.risk_level.value,
            details=risk_res.summary,
        ))

        # Step 3: Medical Knowledge Agent (only when useful / requested)
        knowledge_res = None
        if include_knowledge:
            step_t0 = time.time()
            clean_name = metric_type.replace("_", " ")
            if monitoring_res.status == "deviation":
                query = f"What clinical guidelines exist for managing significant changes or deviations in {clean_name}?"
            elif monitoring_res.is_urgent:
                query = f"Emergency guidelines for acute {clean_name} crisis."
            else:
                query = f"Normal reference ranges and health recommendations for {clean_name}."

            knowledge_res = self.knowledge_agent.query_knowledge(
                user_id=user_id,
                question=query,
                n_results=2,
            )
            steps.append(ExecutionStepLog(
                agent_name="MedicalKnowledgeAgent",
                started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat(),
                duration_ms=int((time.time() - step_t0) * 1000),
                status=knowledge_res.status,
                details=f"Retrieved {len(knowledge_res.citations)} citation(s).",
            ))

        # Step 4: Notification Agent
        step_t0 = time.time()
        notif_res = self.notification_agent.process_pending_alerts(user_id=user_id)
        steps.append(ExecutionStepLog(
            agent_name="NotificationAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status="completed",
            details=notif_res.summary,
        ))

        if state != OrchestrationState.ESCALATED:
            state = (
                OrchestrationState.DEGRADED
                if knowledge_res and knowledge_res.status == "degraded"
                else OrchestrationState.COMPLETED
            )

        duration_ms = int((time.time() - start_time) * 1000)

        # Formulate consolidated clinical summary
        summary_lines = [f"Assessment for {metric_type.replace('_', ' ').title()}:"]
        summary_lines.append(f"• Monitoring: {monitoring_res.summary}")
        summary_lines.append(f"• Risk Assessment: {risk_res.summary}")
        if safety_escalation:
            summary_lines.append(f"• SAFETY ESCALATION: {safety_escalation['urgent_reason']}")
        if knowledge_res and knowledge_res.citations:
            summary_lines.append(f"• Grounded Knowledge: Supported by {len(knowledge_res.citations)} verified reference(s).")

        summary_response = ConsolidatedHealthSummaryResponse(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_A_NEW_MEASUREMENT,
            orchestration_state=state,
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary_text="\n".join(summary_lines),
            monitoring=monitoring_res,
            risk_assessment=risk_res,
            medical_knowledge=knowledge_res,
            notifications=notif_res,
            safety_escalation=safety_escalation,
            execution_steps=steps,
            duration_ms=duration_ms,
        )

        self._record_audit(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_A_NEW_MEASUREMENT.value,
            status=state.value,
            idempotency_key=idempotency_key,
            input_payload={"metric_type": metric_type, "metric_id": metric_id},
            execution_steps=steps,
            result_summary=summary_response.model_dump(),
            duration_ms=duration_ms,
        )

        return summary_response

    # ============================================================
    # WORKFLOW B — MEDICATION ADHERENCE ASSESSMENT
    # ============================================================

    def run_workflow_b_medication_adherence(
        self,
        user_id: int,
    ) -> ConsolidatedHealthSummaryResponse:
        """
        Workflow B:
        1. Check scheduled dose occurrences and refresh overdue statuses.
        2. Evaluate adherence history.
        3. Generate appropriate reminders without duplicates.
        4. Update in-app alerts.
        """
        start_time = time.time()
        steps: list[ExecutionStepLog] = []

        # Step 1: Generate reminders for due/overdue occurrences
        step_t0 = time.time()
        new_reminders = generate_reminders_for_user(self.db, user_id)
        try:
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.warning("Commit for generated reminders failed: %s", exc)

        steps.append(ExecutionStepLog(
            agent_name="MedicationReminderWorker",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status="completed",
            details=f"Generated {len(new_reminders)} new reminder(s).",
        ))

        # Step 2: Medication Agent evaluation
        step_t0 = time.time()
        med_res = self.medication_agent.evaluate_medications(user_id=user_id)
        steps.append(ExecutionStepLog(
            agent_name="MedicationAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status="completed",
            details=med_res.summary,
        ))

        duration_ms = int((time.time() - start_time) * 1000)

        summary_lines = [
            "Medication Adherence Overview:",
            f"• {med_res.summary}",
        ]
        if med_res.recommendations:
            for rec in med_res.recommendations:
                summary_lines.append(f"• Recommendation: {rec}")

        summary_response = ConsolidatedHealthSummaryResponse(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_B_MEDICATION_ADHERENCE,
            orchestration_state=OrchestrationState.COMPLETED,
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary_text="\n".join(summary_lines),
            medication=med_res,
            execution_steps=steps,
            duration_ms=duration_ms,
        )

        idempotency_key = self._generate_idempotency_key(
            user_id,
            WorkflowType.WORKFLOW_B_MEDICATION_ADHERENCE.value,
            {"medications_count": med_res.active_medications_count},
        )

        self._record_audit(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_B_MEDICATION_ADHERENCE.value,
            status=OrchestrationState.COMPLETED.value,
            idempotency_key=idempotency_key,
            input_payload={"user_id": user_id},
            execution_steps=steps,
            result_summary=summary_response.model_dump(),
            duration_ms=duration_ms,
        )

        return summary_response

    # ============================================================
    # WORKFLOW C — COMPREHENSIVE PATIENT HEALTH SUMMARY
    # ============================================================

    def run_workflow_c_health_summary(
        self,
        user_id: int,
        primary_metric: str = "blood_glucose",
    ) -> ConsolidatedHealthSummaryResponse:
        """
        Workflow C:
        1. Retrieve recent health measurements across metrics.
        2. Calculate trends using deterministic analytics.
        3. Retrieve medication adherence metrics.
        4. Include relevant monitoring events.
        5. Use RAG for supporting medical explanations (with citations).
        6. Combine findings into structured, explainable summary.
        """
        start_time = time.time()
        steps: list[ExecutionStepLog] = []
        state = OrchestrationState.IN_PROGRESS

        # Step 1: Monitoring Agent
        step_t0 = time.time()
        monitoring_res = self.monitoring_agent.analyze_metrics(
            user_id=user_id,
            metric_type=primary_metric,
        )
        steps.append(ExecutionStepLog(
            agent_name="MonitoringAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status=monitoring_res.status,
            details=monitoring_res.summary,
        ))

        # Check for Workflow D Escalation
        safety_escalation = None
        if monitoring_res.is_urgent:
            state = OrchestrationState.ESCALATED
            safety_escalation = {
                "level": "CRITICAL_PHYSIOLOGICAL_VALUE",
                "urgent_reason": monitoring_res.urgent_reason,
                "guidance": EMERGENCY_GUIDANCE,
            }

        # Step 2: Risk Assessment Agent
        step_t0 = time.time()
        risk_res = self.risk_agent.evaluate_risk(
            user_id=user_id,
            metric_type=primary_metric,
        )
        steps.append(ExecutionStepLog(
            agent_name="RiskAssessmentAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status=risk_res.risk_level.value,
            details=risk_res.summary,
        ))

        # Step 3: Medication Agent
        step_t0 = time.time()
        med_res = self.medication_agent.evaluate_medications(user_id=user_id)
        steps.append(ExecutionStepLog(
            agent_name="MedicationAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status="completed",
            details=med_res.summary,
        ))

        # Step 4: Medical Knowledge Agent
        step_t0 = time.time()
        query = f"Provide general health maintenance guidelines and standard clinical targets for {primary_metric.replace('_', ' ')}."
        knowledge_res = self.knowledge_agent.query_knowledge(
            user_id=user_id,
            question=query,
            n_results=2,
        )
        steps.append(ExecutionStepLog(
            agent_name="MedicalKnowledgeAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status=knowledge_res.status,
            details=f"Retrieved {len(knowledge_res.citations)} citation(s).",
        ))

        # Step 5: Notification Agent
        step_t0 = time.time()
        notif_res = self.notification_agent.process_pending_alerts(user_id=user_id)
        steps.append(ExecutionStepLog(
            agent_name="NotificationAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status="completed",
            details=notif_res.summary,
        ))

        if state != OrchestrationState.ESCALATED:
            state = (
                OrchestrationState.DEGRADED
                if knowledge_res.status == "degraded"
                else OrchestrationState.COMPLETED
            )

        duration_ms = int((time.time() - start_time) * 1000)

        # Build structured text summary
        summary_lines = [
            "🏥 HealthGuard AI Consolidated Health Summary:",
            f"• Primary Metric ({primary_metric}): {monitoring_res.summary}",
            f"• Risk Profile: {risk_res.summary}",
            f"• Medications: {med_res.summary}",
        ]
        if safety_escalation:
            summary_lines.append(f"• URGENT SAFETY NOTICE: {safety_escalation['urgent_reason']}")
        if knowledge_res.citations:
            summary_lines.append(f"• Knowledge Grounding: {len(knowledge_res.citations)} clinical source citation(s) attached.")

        summary_response = ConsolidatedHealthSummaryResponse(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_C_HEALTH_SUMMARY,
            orchestration_state=state,
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary_text="\n".join(summary_lines),
            monitoring=monitoring_res,
            risk_assessment=risk_res,
            medication=med_res,
            medical_knowledge=knowledge_res,
            notifications=notif_res,
            safety_escalation=safety_escalation,
            execution_steps=steps,
            duration_ms=duration_ms,
        )

        idempotency_key = self._generate_idempotency_key(
            user_id,
            WorkflowType.WORKFLOW_C_HEALTH_SUMMARY.value,
            {"primary_metric": primary_metric},
        )

        self._record_audit(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_C_HEALTH_SUMMARY.value,
            status=state.value,
            idempotency_key=idempotency_key,
            input_payload={"primary_metric": primary_metric},
            execution_steps=steps,
            result_summary=summary_response.model_dump(),
            duration_ms=duration_ms,
        )

        return summary_response

    # ============================================================
    # WORKFLOW D — SAFETY ESCALATION
    # ============================================================

    def run_workflow_d_safety_escalation(
        self,
        user_id: int,
        metric_type: str,
        value: float,
        unit: str,
        reason: str,
    ) -> ConsolidatedHealthSummaryResponse:
        """
        Workflow D:
        1. Prioritize critical alert.
        2. Provide clear guidance to seek professional medical assistance.
        3. Never autonomously diagnose, prescribe medication, or dial emergency services.
        4. Record event and notification.
        """
        start_time = time.time()
        steps: list[ExecutionStepLog] = []

        step_t0 = time.time()
        safety_escalation = {
            "level": "CRITICAL_ESCALATION",
            "metric_type": metric_type,
            "value": value,
            "unit": unit,
            "urgent_reason": reason,
            "guidance": (
                f"{EMERGENCY_GUIDANCE}\n\n"
                f"Urgent Finding: Your recorded {metric_type.replace('_', ' ')} value of {value} {unit} "
                f"exceeds standard safety thresholds ({reason}).\n"
                "Please seek immediate medical evaluation from a physician, urgent care clinic, "
                "or local emergency department."
            ),
            "disclaimer": (
                "HealthGuard AI is an automated statistical software tool and does not provide "
                "clinical diagnoses or emergency rescue services."
            ),
        }
        steps.append(ExecutionStepLog(
            agent_name="SafetyEscalationAgent",
            started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=int((time.time() - step_t0) * 1000),
            status="escalated",
            details=f"Safety escalation triggered: {reason}",
        ))

        duration_ms = int((time.time() - start_time) * 1000)

        summary_response = ConsolidatedHealthSummaryResponse(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_D_SAFETY_ESCALATION,
            orchestration_state=OrchestrationState.ESCALATED,
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary_text=f"CRITICAL SAFETY ESCALATION: {reason}",
            safety_escalation=safety_escalation,
            execution_steps=steps,
            duration_ms=duration_ms,
        )

        idempotency_key = self._generate_idempotency_key(
            user_id,
            WorkflowType.WORKFLOW_D_SAFETY_ESCALATION.value,
            {"metric_type": metric_type, "value": value},
        )

        self._record_audit(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_D_SAFETY_ESCALATION.value,
            status=OrchestrationState.ESCALATED.value,
            idempotency_key=idempotency_key,
            input_payload={"metric_type": metric_type, "value": value, "unit": unit, "reason": reason},
            execution_steps=steps,
            result_summary=summary_response.model_dump(),
            duration_ms=duration_ms,
        )

        return summary_response
