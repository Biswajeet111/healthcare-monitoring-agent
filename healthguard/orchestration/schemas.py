"""
Pydantic schemas and state definitions for HealthGuard AI Phase 8 Agentic Orchestration.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ============================================================
# ENUMS
# ============================================================

class OrchestrationState(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    DEGRADED = "degraded"


class WorkflowType(str, Enum):
    WORKFLOW_A_NEW_MEASUREMENT = "workflow_a_new_measurement"
    WORKFLOW_B_MEDICATION_ADHERENCE = "workflow_b_medication_adherence"
    WORKFLOW_C_HEALTH_SUMMARY = "workflow_c_health_summary"
    WORKFLOW_D_SAFETY_ESCALATION = "workflow_d_safety_escalation"


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"
    INSUFFICIENT_DATA = "insufficient_data"


# ============================================================
# AGENT RESULTS
# ============================================================

class MonitoringAgentResult(BaseModel):
    status: str = "normal"  # normal, deviation, insufficient_data, urgent_review
    metric_type: str
    latest_value: Optional[float] = None
    unit: str
    summary: str
    statistical_status: str = "routine_monitoring"
    is_urgent: bool = False
    urgent_reason: Optional[str] = None
    monitoring_priority: str = "routine"
    recent_readings_count: int = 0
    disclaimer: str = (
        "Monitoring observations represent statistical variability and "
        "trend metrics, not clinical diagnoses."
    )


class RiskAssessmentAgentResult(BaseModel):
    risk_level: RiskLevel = RiskLevel.LOW
    rule_based_findings: list[dict[str, Any]] = Field(default_factory=list)
    experimental_ml_estimates: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    is_experimental: bool = False
    disclaimer: str = (
        "Rule-based findings reflect statistical observations. "
        "Any experimental machine learning estimates are unvalidated research "
        "demonstrations and must NEVER be used as a medical diagnosis."
    )


class MedicationAgentResult(BaseModel):
    active_medications_count: int = 0
    overall_adherence_percentage: Optional[float] = None
    overdue_doses_count: int = 0
    missed_doses_count: int = 0
    taken_doses_count: int = 0
    pending_reminders: list[dict[str, Any]] = Field(default_factory=list)
    adherence_by_medication: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Medication adherence information is for user tracking only. "
        "The system never modifies medication schedules or dosages."
    )


class MedicalCitation(BaseModel):
    title: str
    source_organization: Optional[str] = None
    source_url: Optional[str] = None
    excerpt: str


class MedicalKnowledgeAgentResult(BaseModel):
    status: str = "success"  # success, degraded, skipped
    query: Optional[str] = None
    explanation: str
    citations: list[MedicalCitation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    is_emergency: bool = False
    emergency_guidance: Optional[str] = None
    disclaimer: str = (
        "Retrieved medical knowledge provides general clinical reference "
        "information and does not constitute individual medical advice."
    )


class NotificationAgentResult(BaseModel):
    notifications_created: list[dict[str, Any]] = Field(default_factory=list)
    suppressed_count: int = 0
    summary: str


# ============================================================
# AUDIT & WORKFLOW REPORTS
# ============================================================

class ExecutionStepLog(BaseModel):
    agent_name: str
    started_at: str
    completed_at: str
    duration_ms: int
    status: str
    details: Optional[str] = None


class ConsolidatedHealthSummaryResponse(BaseModel):
    user_id: int
    workflow_type: WorkflowType
    orchestration_state: OrchestrationState
    generated_at: str
    summary_text: str
    monitoring: Optional[MonitoringAgentResult] = None
    risk_assessment: Optional[RiskAssessmentAgentResult] = None
    medication: Optional[MedicationAgentResult] = None
    medical_knowledge: Optional[MedicalKnowledgeAgentResult] = None
    notifications: Optional[NotificationAgentResult] = None
    safety_escalation: Optional[dict[str, Any]] = None
    execution_steps: list[ExecutionStepLog] = Field(default_factory=list)
    duration_ms: int = 0
    disclaimer: str = (
        "HealthGuard AI is an informational and health monitoring system. "
        "It does not provide medical diagnoses, clinical treatment plans, or "
        "emergency dispatch services. Always consult a licensed healthcare professional."
    )


class AgentExecutionAuditResponse(BaseModel):
    id: int
    user_id: int
    workflow_type: str
    status: str
    idempotency_key: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None
    summary: Optional[str] = None
    error_message: Optional[str] = None


class RunAssessmentRequest(BaseModel):
    metric_type: Optional[str] = "blood_glucose"
    include_knowledge: bool = True
    include_adherence: bool = True
    experimental_ml: bool = False
    ml_features: Optional[dict[str, Any]] = None


class MedicationCheckRequest(BaseModel):
    force_refresh: bool = False
