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
from healthguard.rag.safety import (
    EMERGENCY_GUIDANCE,
    check_unsafe_request,
    validate_response,
)
from healthguard.services.medication_reminder_service import generate_reminders_for_user
from healthguard.orchestration.planner import classify_request_intent, select_next_action
from healthguard.orchestration.tools import (
    ALLOWED_TOOLS,
    ToolValidationError,
    build_request_tool_scope,
    canonical_tool_signature,
    evaluate_domain_coverage,
    execute_allowlisted_tool,
    get_minimal_user_context,
    validate_tool_against_request_scope,
    validate_tool_call,
)

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

    # ============================================================
    # DYNAMIC AGENTIC WORKFLOW (ITERATIVE DECISION-EXECUTION LOOP)
    # ============================================================

    def run_dynamic_workflow(
        self,
        user_id: int,
        query: str,
        preferred_metric: Optional[str] = None,
        max_steps: int = 6,
        experimental_ml: bool = False,
        ml_features: Optional[dict[str, Any]] = None,
        allow_notification_delivery: bool = False,
        overall_timeout_seconds: float = 90.0,
    ) -> ConsolidatedHealthSummaryResponse:
        """
        Execute an iterative Decision -> Execution -> Observation loop:
        1. Screen the user's request with deterministic healthcare safety checks.
        2. Retrieve minimal privacy-preserving user context.
        3. At each iteration (up to `max_steps`, capped at 8):
           a. Ask the planner (`select_next_action`) to select the next allowlisted tool or `"finish"`
              based on the request, minimal context, and observations from prior steps.
           b. Validate the proposed tool call and reject duplicates or unauthorized parameters.
           c. Execute the tool with the backend-authenticated `user_id`.
           d. Capture the structured result and feed a sanitized observation back into the loop.
        4. Synthesize a grounded final response, validate response safety, and persist the audit trace.
        """
        start_time = time.time()
        clean_query = (query or "").strip()
        bounded_max_steps = max(1, min(int(max_steps or 6), 8))

        steps: list[ExecutionStepLog] = []
        observations: list[dict[str, Any]] = []
        executed_signatures: set[str] = set()
        selected_agents: list[str] = []
        planner_modes_seen: set[str] = set()

        monitoring_res: Optional[MonitoringAgentResult] = None
        risk_res: Optional[RiskAssessmentAgentResult] = None
        med_res: Optional[MedicationAgentResult] = None
        knowledge_res: Optional[MedicalKnowledgeAgentResult] = None
        notif_res: Optional[NotificationAgentResult] = None
        safety_escalation: Optional[dict[str, Any]] = None
        detected_intent: Optional[str] = None
        final_guidance: Optional[str] = None
        termination_reason: Optional[str] = None

        # 1. Deterministic Pre-Execution Medical Safety Gate
        safety_screen = check_unsafe_request(clean_query)
        if not safety_screen.get("safe_to_process", True):
            step_t0 = time.time()
            is_emerg = bool(safety_screen.get("is_emergency", False))
            reason_msg = str(safety_screen.get("reason") or "Request blocked by medical safety policy.")

            if is_emerg:
                state = OrchestrationState.ESCALATED
                detected_intent = "emergency_escalation"
                termination_reason = "Emergency symptom pattern detected; escalated immediately."
                safety_escalation = {
                    "level": "EMERGENCY_SYMPTOM_DETECTED",
                    "urgent_reason": "User request matched potential medical emergency symptoms.",
                    "guidance": safety_screen.get("emergency_guidance") or EMERGENCY_GUIDANCE,
                    "message": reason_msg,
                }
                agent_label = "SafetyEscalationAgent"
                step_status = "escalated"
            else:
                state = OrchestrationState.COMPLETED
                detected_intent = "safety_boundary_refusal"
                termination_reason = "Unsafe diagnostic or prescription request refused by deterministic safety gate."
                agent_label = "MedicalSafetyGate"
                step_status = "refused"

            steps.append(
                ExecutionStepLog(
                    step_order=1,
                    agent_name=agent_label,
                    tool_name="check_unsafe_request",
                    started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    duration_ms=int((time.time() - step_t0) * 1000),
                    status=step_status,
                    selection_reason="Deterministic pre-execution medical safety screening.",
                    details=termination_reason,
                    intermediate_output={
                        "is_emergency": is_emerg,
                        "has_unsafe_request": bool(safety_screen.get("has_unsafe_request", False)),
                    },
                )
            )
            selected_agents.append(agent_label)
            duration_ms = int((time.time() - start_time) * 1000)

            summary_response = ConsolidatedHealthSummaryResponse(
                user_id=user_id,
                workflow_type=WorkflowType.WORKFLOW_DYNAMIC_AGENTIC,
                orchestration_state=state,
                generated_at=datetime.now(timezone.utc).isoformat(),
                summary_text=reason_msg,
                user_request=clean_query,
                detected_intent=detected_intent,
                planner_mode="deterministic_safety_gate",
                selected_agents=selected_agents,
                termination_reason=termination_reason,
                safety_escalation=safety_escalation,
                execution_steps=steps,
                duration_ms=duration_ms,
            )
            self._record_audit(
                user_id=user_id,
                workflow_type=WorkflowType.WORKFLOW_DYNAMIC_AGENTIC.value,
                status=state.value,
                idempotency_key=None,
                input_payload={"query": clean_query, "max_steps": bounded_max_steps},
                execution_steps=steps,
                result_summary=summary_response.model_dump(),
                duration_ms=duration_ms,
            )
            return summary_response

        # 2. Retrieve Minimal Privacy-Preserving User Context & Build Request Scope
        minimal_context = get_minimal_user_context(self.db, user_id)
        initial_intent = classify_request_intent(clean_query)
        request_scope = build_request_tool_scope(
            user_request=clean_query,
            initial_intent=initial_intent,
            minimal_context=minimal_context,
            preferred_metric=preferred_metric,
            allow_notification_delivery=allow_notification_delivery,
        )
        detected_intent = initial_intent
        primary_metric = request_scope.primary_metric

        monitoring_by_metric: dict[str, MonitoringAgentResult] = {}
        risk_by_metric: dict[str, RiskAssessmentAgentResult] = {}
        total_planner_llm_ms = 0
        total_agent_execution_ms = 0
        total_rag_generation_ms = 0

        # 3. Iterative Decision -> Execution -> Observation Loop
        for step_num in range(1, bounded_max_steps + 1):
            elapsed = time.time() - start_time
            if elapsed >= overall_timeout_seconds:
                termination_reason = (
                    f"Workflow stopped after reaching overall timeout ({overall_timeout_seconds:.0f}s)."
                )
                break

            planner_step = select_next_action(
                user_request=clean_query,
                minimal_context=minimal_context,
                observations=observations,
                executed_signatures=executed_signatures,
                preferred_metric=preferred_metric or primary_metric,
                allow_notification_delivery=allow_notification_delivery,
                request_scope=request_scope,
            )
            total_planner_llm_ms += int(planner_step.planner_llm_ms or 0)
            planner_modes_seen.add(planner_step.planner_mode)
            decision = planner_step.decision

            # Preserve initial user intent throughout execution unless 0 data exists
            if decision.detected_intent == "insufficient_information":
                detected_intent = "insufficient_information"
            else:
                detected_intent = initial_intent

            if decision.final_guidance:
                final_guidance = decision.final_guidance

            # Check termination decision from planner
            if decision.action == "finish":
                termination_reason = decision.selection_reason
                if step_num == 1 and planner_step.rejection_notes:
                    # Record a trace note if an initial invalid LLM tool was rejected before finishing
                    steps.append(
                        ExecutionStepLog(
                            step_order=1,
                            agent_name="OrchestratorPlanner",
                            tool_name="finish",
                            started_at=datetime.now(timezone.utc).isoformat(),
                            completed_at=datetime.now(timezone.utc).isoformat(),
                            duration_ms=0,
                            status="completed",
                            selection_reason=decision.selection_reason,
                            details=final_guidance or decision.selection_reason,
                            error_recovery="; ".join(planner_step.rejection_notes),
                        )
                    )
                break

            # Validate proposed tool call, request scope, and duplicate signature at orchestrator boundary
            step_t0 = time.time()
            try:
                clean_tool, validated_args = validate_tool_call(
                    decision.tool_name or "",
                    decision.tool_args,
                )
                validate_tool_against_request_scope(
                    tool_name=clean_tool,
                    validated_args=validated_args,
                    request_scope=request_scope,
                    observations=observations,
                )
                sig = canonical_tool_signature(clean_tool, validated_args)
                if sig in executed_signatures:
                    termination_reason = (
                        f"Duplicate tool call prevented ({clean_tool}); terminating loop safely."
                    )
                    break
                executed_signatures.add(sig)
            except ToolValidationError as val_err:
                termination_reason = f"Rejected invalid tool proposal: {val_err}"
                steps.append(
                    ExecutionStepLog(
                        step_order=step_num,
                        agent_name="OrchestratorValidator",
                        tool_name=str(decision.tool_name or "invalid_tool"),
                        started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        duration_ms=int((time.time() - step_t0) * 1000),
                        status="rejected",
                        selection_reason=decision.selection_reason,
                        details=str(val_err),
                        error_recovery="Blocked invalid tool request before execution.",
                    )
                )
                break

            # Execute validated tool with error boundary
            try:
                outcome = execute_allowlisted_tool(
                    db=self.db,
                    user_id=user_id,
                    tool_name=clean_tool,
                    validated_args=validated_args,
                    monitoring_agent=self.monitoring_agent,
                    risk_agent=self.risk_agent,
                    medication_agent=self.medication_agent,
                    knowledge_agent=self.knowledge_agent,
                    notification_agent=self.notification_agent,
                    experimental_ml_enabled=experimental_ml,
                    ml_features=ml_features,
                    allow_notification_delivery=allow_notification_delivery,
                )
            except Exception as tool_exc:
                logger.warning("Tool '%s' raised an exception: %s", clean_tool, tool_exc)
                err_duration = int((time.time() - step_t0) * 1000)
                total_agent_execution_ms += err_duration
                agent_name = ALLOWED_TOOLS.get(clean_tool, {}).get("agent_name", "UnknownAgent")
                recovery_note = f"Recovered from {clean_tool} error: {tool_exc}"
                if planner_step.rejection_notes:
                    recovery_note = "; ".join(planner_step.rejection_notes + [recovery_note])

                steps.append(
                    ExecutionStepLog(
                        step_order=step_num,
                        agent_name=agent_name,
                        tool_name=clean_tool,
                        started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        duration_ms=err_duration,
                        status="failed",
                        selection_reason=decision.selection_reason,
                        details=f"Tool execution failed: {tool_exc}",
                        intermediate_output={"error": str(tool_exc)},
                        error_recovery=recovery_note,
                    )
                )
                observations.append({
                    "step": step_num,
                    "tool_name": clean_tool,
                    "status": "failed",
                    "observation": f"Tool {clean_tool} failed with error: {tool_exc}",
                    "intermediate_output": {"error": str(tool_exc)},
                })
                continue

            if clean_tool == "query_medical_knowledge":
                total_rag_generation_ms += outcome.duration_ms
            else:
                total_agent_execution_ms += outcome.duration_ms

            # Merge structured agent output (always prioritizing primary_metric)
            if outcome.agent_name not in selected_agents:
                selected_agents.append(outcome.agent_name)

            if outcome.monitoring_result is not None:
                m_res = outcome.monitoring_result
                monitoring_by_metric[m_res.metric_type] = m_res
                monitoring_res = monitoring_by_metric.get(primary_metric) or m_res
                if m_res.is_urgent:
                    safety_escalation = {
                        "level": "CRITICAL_PHYSIOLOGICAL_VALUE",
                        "urgent_reason": m_res.urgent_reason,
                        "guidance": (
                            f"{EMERGENCY_GUIDANCE}\n\n"
                            f"Action Required: Your recorded measurement ({m_res.latest_value} "
                            f"{m_res.unit}) indicates a potentially critical physiological state. "
                            "Seek immediate professional medical evaluation."
                        ),
                    }
            if outcome.risk_result is not None:
                r_res = outcome.risk_result
                r_metric = str(validated_args.get("metric_type") or primary_metric)
                risk_by_metric[r_metric] = r_res
                risk_res = risk_by_metric.get(primary_metric) or r_res
            if outcome.medication_result is not None:
                med_res = outcome.medication_result
            if outcome.knowledge_result is not None:
                knowledge_res = outcome.knowledge_result
                if knowledge_res.is_emergency and not safety_escalation:
                    safety_escalation = {
                        "level": "EMERGENCY_KNOWLEDGE_QUERY",
                        "urgent_reason": "Emergency medical topic detected during knowledge retrieval.",
                        "guidance": knowledge_res.emergency_guidance or EMERGENCY_GUIDANCE,
                    }
            if outcome.notification_result is not None:
                notif_res = outcome.notification_result

            combined_recovery_notes: list[str] = []
            if planner_step.rejection_notes:
                combined_recovery_notes.extend(planner_step.rejection_notes)
            if outcome.error_recovery:
                combined_recovery_notes.append(outcome.error_recovery)

            step_inter = dict(outcome.intermediate_output or {})
            step_inter["planner_llm_ms"] = int(planner_step.planner_llm_ms or 0)

            steps.append(
                ExecutionStepLog(
                    step_order=step_num,
                    agent_name=outcome.agent_name,
                    tool_name=outcome.tool_name,
                    started_at=datetime.fromtimestamp(step_t0, timezone.utc).isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    duration_ms=outcome.duration_ms,
                    status=outcome.status,
                    selection_reason=decision.selection_reason,
                    details=outcome.details,
                    intermediate_output=step_inter,
                    error_recovery="; ".join(combined_recovery_notes) if combined_recovery_notes else None,
                )
            )

            observations.append({
                "step": step_num,
                "tool_name": outcome.tool_name,
                "status": outcome.status,
                "observation": outcome.observation_text,
                "intermediate_output": outcome.intermediate_output,
            })
        else:
            termination_reason = f"Reached configured maximum execution steps ({bounded_max_steps})."

        # Ensure termination_reason accurately matches the executed agents, intent, and domain coverage
        final_coverage = evaluate_domain_coverage(request_scope, observations, minimal_context)
        if selected_agents and termination_reason:
            last_agent = steps[-1].agent_name if steps else None
            if (
                "medical knowledge retrieval completed" in termination_reason.lower()
                and last_agent != "MedicalKnowledgeAgent"
            ):
                termination_reason = (
                    f"Completed {detected_intent.replace('_', ' ')} workflow after executing "
                    f"{', '.join(selected_agents)}."
                )
            if (
                final_coverage["unaddressed_domains"]
                or final_coverage["failed_domains"]
                or final_coverage["unavailable_domains"]
            ) and "all requested" in termination_reason.lower():
                completed_str = ", ".join(final_coverage["completed_domains"]) or "none"
                unavail_str = (
                    f"; unavailable (no records): {', '.join(final_coverage['unavailable_domains'])}"
                    if final_coverage["unavailable_domains"]
                    else ""
                )
                failed_str = (
                    f"; failed: {', '.join(final_coverage['failed_domains'])}"
                    if final_coverage["failed_domains"]
                    else ""
                )
                unaddr_str = (
                    f"; unaddressed: {', '.join(final_coverage['unaddressed_domains'])}"
                    if final_coverage["unaddressed_domains"]
                    else ""
                )
                termination_reason = (
                    f"Workflow finished across requested domains "
                    f"(addressed: [{completed_str}]{unavail_str}{failed_str}{unaddr_str}) "
                    f"after executing {', '.join(selected_agents)}."
                )

        # 4. Determine Final Orchestration State
        if safety_escalation is not None:
            state = OrchestrationState.ESCALATED
        elif any(s.status in ("failed", "degraded") for s in steps):
            state = OrchestrationState.DEGRADED
        else:
            state = OrchestrationState.COMPLETED

        planner_mode = (
            "llm_assisted"
            if "llm_assisted" in planner_modes_seen
            else "deterministic_fallback"
        )

        # 5. Synthesize Grounded Final Summary & Validate Safety
        synth_t0 = time.time()
        summary_lines: list[str] = []
        if final_guidance and not selected_agents:
            summary_lines.append(final_guidance)
        else:
            header_intent = (detected_intent or "dynamic_assessment").replace("_", " ").title()
            summary_lines.append(f"Dynamic Agentic Response ({header_intent}):")
            if final_guidance and detected_intent == "insufficient_information":
                summary_lines.append(f"• {final_guidance}")

            if monitoring_res:
                metric_label = monitoring_res.metric_type.replace("_", " ").title()
                if monitoring_res.latest_value is not None:
                    summary_lines.append(
                        f"• Recorded Measurement ({metric_label}): Latest reading is "
                        f"{monitoring_res.latest_value} {monitoring_res.unit} "
                        f"(across {monitoring_res.recent_readings_count} recent reading(s))."
                    )
                else:
                    summary_lines.append(
                        f"• Recorded Measurement ({metric_label}): {monitoring_res.summary}"
                    )

                if monitoring_res.status == "deviation" or monitoring_res.statistical_status == "statistical_deviation_detected":
                    summary_lines.append(
                        f"• Statistical Deviation Analysis: Statistical deviation detected for "
                        f"{monitoring_res.metric_type.replace('_', ' ')} "
                        f"(statistical_status='{monitoring_res.statistical_status}', "
                        f"monitoring_priority='{monitoring_res.monitoring_priority}'). "
                        f"{monitoring_res.summary} This represents statistical variability relative "
                        "to your baseline readings, not a clinical diagnosis."
                    )
                else:
                    summary_lines.append(
                        f"• Statistical Deviation Analysis ({metric_label}): "
                        f"Status is '{monitoring_res.status}' "
                        f"(statistical_status='{monitoring_res.statistical_status}'). "
                        f"{monitoring_res.summary}"
                    )

            if risk_res:
                rule_cat = risk_res.risk_level.value
                if risk_res.rule_based_findings:
                    f0 = risk_res.rule_based_findings[0]
                    f_dir = f0.get("direction", "unchanged")
                    f_mean = f0.get("mean")
                    f_unit = f0.get("unit") or (monitoring_res.unit if monitoring_res else "")
                    mean_str = f"{float(f_mean):.1f} {f_unit}".strip() if f_mean is not None else "N/A"
                    summary_lines.append(
                        f"• Rule-Based Risk & Trend Classification: Rule-based risk category is "
                        f"'{rule_cat}' ({rule_cat.upper()} — a deterministic rule-based threshold "
                        f"classification, not a confirmed medical condition). "
                        f"Trend direction is {f_dir} with a 30-reading window mean of {mean_str}."
                    )
                else:
                    summary_lines.append(
                        f"• Rule-Based Risk & Trend Classification: Rule-based risk category is "
                        f"'{rule_cat}'. {risk_res.summary}"
                    )

            if med_res:
                med_names = [
                    f"{m.get('name')} ({m.get('dosage')})"
                    for m in (med_res.adherence_by_medication or [])
                    if m.get("name")
                ]
                active_meds_detail = (
                    f"{med_res.active_medications_count} ({', '.join(med_names)})"
                    if med_names
                    else str(med_res.active_medications_count)
                )
                overall_adh_str = (
                    f"{med_res.overall_adherence_percentage}%"
                    if med_res.overall_adherence_percentage is not None
                    else "N/A (no evaluable past doses)"
                )
                summary_lines.append(
                    f"• Medication Adherence: Active medications: {active_meds_detail}. "
                    f"Overall adherence: {overall_adh_str}. "
                    f"Taken doses: {med_res.taken_doses_count}, "
                    f"Missed doses: {med_res.missed_doses_count}, "
                    f"Overdue/unconfirmed doses: {med_res.overdue_doses_count}. "
                    f"{med_res.summary}"
                )
                for rec in med_res.recommendations[:2]:
                    summary_lines.append(f"  - {rec}")
            elif "medication_adherence" in request_scope.requested_domains:
                med_cov_status = final_coverage["domain_status"].get("medication_adherence", "unaddressed")
                summary_lines.append(
                    f"• Medication Adherence: Requested domain could not be completed (status='{med_cov_status}')."
                )

            if knowledge_res:
                if "medical_documents" in request_scope.requested_domains or detected_intent in (
                    "comprehensive_summary",
                    "medical_document_question",
                ):
                    summary_lines.append(
                        f"• Uploaded Medical Document & Knowledge Findings: {knowledge_res.explanation}"
                    )
                else:
                    summary_lines.append(
                        f"• Retrieved Medical Knowledge: {knowledge_res.explanation}"
                    )
                if knowledge_res.citations:
                    cite_titles = ", ".join(c.title for c in knowledge_res.citations[:4])
                    summary_lines.append(
                        f"  ({len(knowledge_res.citations)} verified source citation(s) retrieved: {cite_titles}.)"
                    )

            if notif_res:
                summary_lines.append(f"• Alerts & Notifications: {notif_res.summary}")

            if safety_escalation:
                summary_lines.append(f"• SAFETY ESCALATION: {safety_escalation.get('urgent_reason')}")

            if any([monitoring_res, risk_res, med_res, knowledge_res]):
                summary_lines.append(
                    "• General Educational Guidance: Statistical deviations and deterministic "
                    "rule-based risk categories are informational monitoring indicators rather than "
                    "clinical conclusions or diagnoses. Please review your measurement trends, "
                    "medication adherence, and medical reports with a qualified healthcare professional."
                )

            if not any([monitoring_res, risk_res, med_res, knowledge_res, notif_res]):
                summary_lines.append(
                    final_guidance
                    or "No relevant health records were available to complete this request."
                )

        raw_summary_text = "\n".join(summary_lines)
        safety_val = validate_response(raw_summary_text)
        safe_summary_text = safety_val.get("sanitized", raw_summary_text)
        response_synthesis_ms = int((time.time() - synth_t0) * 1000)

        duration_ms = int((time.time() - start_time) * 1000)
        latency_breakdown_ms = {
            "planner_llm_ms": total_planner_llm_ms,
            "agent_execution_ms": total_agent_execution_ms,
            "rag_generation_ms": total_rag_generation_ms,
            "response_synthesis_ms": response_synthesis_ms,
            "total_duration_ms": duration_ms,
        }

        summary_response = ConsolidatedHealthSummaryResponse(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_DYNAMIC_AGENTIC,
            orchestration_state=state,
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary_text=safe_summary_text,
            user_request=clean_query,
            detected_intent=detected_intent,
            planner_mode=planner_mode,
            selected_agents=selected_agents,
            termination_reason=termination_reason,
            monitoring=monitoring_res,
            risk_assessment=risk_res,
            medication=med_res,
            medical_knowledge=knowledge_res,
            notifications=notif_res,
            safety_escalation=safety_escalation,
            execution_steps=steps,
            duration_ms=duration_ms,
            latency_breakdown_ms=latency_breakdown_ms,
        )

        self._record_audit(
            user_id=user_id,
            workflow_type=WorkflowType.WORKFLOW_DYNAMIC_AGENTIC.value,
            status=state.value,
            idempotency_key=None,
            input_payload={
                "query": clean_query,
                "preferred_metric": preferred_metric,
                "max_steps": bounded_max_steps,
                "planner_mode": planner_mode,
                "latency_breakdown_ms": latency_breakdown_ms,
            },
            execution_steps=steps,
            result_summary=summary_response.model_dump(),
            duration_ms=duration_ms,
        )

        return summary_response
