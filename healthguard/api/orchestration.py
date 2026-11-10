"""
Agentic Orchestration API Endpoints — Phase 8

Exposes authenticated endpoints for:
- Running authorized multi-agent health assessments (Workflow A)
- Retrieving consolidated patient health summaries (Workflow C)
- Executing medication adherence checks and generating alerts (Workflow B)
- Evaluating emergency safety escalations (Workflow D)
- Reviewing agent execution history and audit trails
- Accessing agent-generated alerts and recommendations
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.core.dependencies import get_current_user
from healthguard.database import models
from healthguard.database.session import get_db
from healthguard.orchestration.orchestrator import AgenticOrchestrator
from healthguard.orchestration.schemas import (
    AgentExecutionAuditResponse,
    ConsolidatedHealthSummaryResponse,
    MedicationCheckRequest,
    RunAssessmentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/orchestration",
    tags=["Agentic Orchestration"],
)


def _verify_user_ownership(requested_user_id: int, current_user: models.UserProfile):
    if requested_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this user's data",
        )


@router.post(
    "/assess",
    response_model=ConsolidatedHealthSummaryResponse,
    summary="Run an authorized multi-agent health assessment",
)
def run_health_assessment(
    request: RunAssessmentRequest,
    user_id: Optional[int] = Query(None, description="Target user ID (must match authenticated user)"),
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Execute Workflow A: New health measurement assessment.
    Coordinates Monitoring, Risk Assessment, Medical Knowledge, and Notification agents.
    """
    target_user_id = user_id if user_id is not None else current_user.id
    _verify_user_ownership(target_user_id, current_user)

    orchestrator = AgenticOrchestrator(db)
    result = orchestrator.run_workflow_a_measurement(
        user_id=target_user_id,
        metric_type=request.metric_type or "blood_glucose",
        include_knowledge=request.include_knowledge,
        experimental_ml=request.experimental_ml,
        ml_features=request.ml_features,
    )
    return result


@router.get(
    "/summary",
    response_model=ConsolidatedHealthSummaryResponse,
    summary="Retrieve consolidated patient health summary",
)
def get_consolidated_summary(
    user_id: Optional[int] = Query(None, description="Target user ID (must match authenticated user)"),
    primary_metric: str = Query("blood_glucose", description="Primary metric for trend evaluation"),
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Execute Workflow C: Consolidated patient health summary.
    Combines deterministic analytics, medication adherence, recent monitoring events,
    and grounded clinical citations.
    """
    target_user_id = user_id if user_id is not None else current_user.id
    _verify_user_ownership(target_user_id, current_user)

    orchestrator = AgenticOrchestrator(db)
    result = orchestrator.run_workflow_c_health_summary(
        user_id=target_user_id,
        primary_metric=primary_metric,
    )
    return result


@router.post(
    "/medication-check",
    response_model=ConsolidatedHealthSummaryResponse,
    summary="Run medication adherence evaluation",
)
def run_medication_check(
    request: MedicationCheckRequest = MedicationCheckRequest(),
    user_id: Optional[int] = Query(None, description="Target user ID (must match authenticated user)"),
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Execute Workflow B: Medication adherence evaluation.
    Checks scheduled dose occurrences, adherence history, and pending reminders.
    """
    target_user_id = user_id if user_id is not None else current_user.id
    _verify_user_ownership(target_user_id, current_user)

    orchestrator = AgenticOrchestrator(db)
    result = orchestrator.run_workflow_b_medication_adherence(user_id=target_user_id)
    return result


@router.get(
    "/history",
    response_model=list[AgentExecutionAuditResponse],
    summary="View agent execution history and audit logs",
)
def get_agent_execution_history(
    user_id: Optional[int] = Query(None, description="Target user ID"),
    limit: int = Query(20, ge=1, le=100),
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve chronological execution audit logs for the authenticated user.
    """
    target_user_id = user_id if user_id is not None else current_user.id
    _verify_user_ownership(target_user_id, current_user)

    stmt = (
        select(models.AgentExecutionAudit)
        .where(models.AgentExecutionAudit.user_id == target_user_id)
        .order_by(models.AgentExecutionAudit.created_at.desc())
        .limit(limit)
    )
    records = list(db.scalars(stmt).all())

    history = []
    for rec in records:
        summary_str = None
        if rec.result_summary:
            try:
                data = json.loads(rec.result_summary)
                summary_str = data.get("summary_text")
            except Exception:
                summary_str = rec.result_summary[:200]

        history.append(
            AgentExecutionAuditResponse(
                id=rec.id,
                user_id=rec.user_id,
                workflow_type=rec.workflow_type,
                status=rec.status,
                idempotency_key=rec.idempotency_key,
                created_at=rec.created_at.isoformat() if rec.created_at else "",
                completed_at=rec.completed_at.isoformat() if rec.completed_at else None,
                duration_ms=rec.duration_ms,
                summary=summary_str,
                error_message=rec.error_message,
            )
        )
    return history


@router.get(
    "/alerts",
    summary="View agent-generated alerts, safety escalations, and recommendations",
)
def get_orchestration_alerts(
    user_id: Optional[int] = Query(None, description="Target user ID"),
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Aggregates active monitoring events, urgent safety notices, and medication reminders.
    """
    target_user_id = user_id if user_id is not None else current_user.id
    _verify_user_ownership(target_user_id, current_user)

    # 1. Unacknowledged monitoring events
    events_stmt = (
        select(models.MonitoringEvent)
        .where(
            models.MonitoringEvent.user_id == target_user_id,
            models.MonitoringEvent.is_acknowledged.is_(False),
        )
        .order_by(models.MonitoringEvent.created_at.desc())
        .limit(10)
    )
    events = list(db.scalars(events_stmt).all())

    # 2. Pending medication reminders
    reminders_stmt = (
        select(models.MedicationReminder)
        .where(
            models.MedicationReminder.user_id == target_user_id,
            models.MedicationReminder.status == "pending",
        )
        .order_by(models.MedicationReminder.created_at.desc())
        .limit(10)
    )
    reminders = list(db.scalars(reminders_stmt).all())

    # 3. Recent safety escalations from agent execution audits
    escalations_stmt = (
        select(models.AgentExecutionAudit)
        .where(
            models.AgentExecutionAudit.user_id == target_user_id,
            models.AgentExecutionAudit.status == "escalated",
        )
        .order_by(models.AgentExecutionAudit.created_at.desc())
        .limit(5)
    )
    escalations = list(db.scalars(escalations_stmt).all())

    return {
        "user_id": target_user_id,
        "unread_monitoring_events": [
            {
                "id": ev.id,
                "metric_type": ev.metric_type,
                "event_type": ev.event_type,
                "event_level": ev.event_level,
                "message": ev.message,
                "created_at": ev.created_at.isoformat() if ev.created_at else "",
            }
            for ev in events
        ],
        "pending_medication_reminders": [
            {
                "id": r.id,
                "occurrence_id": r.occurrence_id,
                "medication_id": r.medication_id,
                "message": r.message,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in reminders
        ],
        "recent_safety_escalations": [
            {
                "id": esc.id,
                "workflow_type": esc.workflow_type,
                "created_at": esc.created_at.isoformat() if esc.created_at else "",
                "details": esc.result_summary,
            }
            for esc in escalations
        ],
    }
