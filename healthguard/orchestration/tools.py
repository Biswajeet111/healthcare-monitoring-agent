"""
Allowlisted Agent Tools & Validation Layer — Dynamic Agentic Orchestration

Exposes the five existing specialized agents through strictly validated,
allowlisted tool interfaces:
1. monitor_health_metric       -> MonitoringAgent
2. assess_health_risk          -> RiskAssessmentAgent
3. check_medication_adherence  -> MedicationAgent
4. query_medical_knowledge     -> MedicalKnowledgeAgent
5. inspect_active_alerts       -> NotificationAgent (read-only inspection)
6. deliver_pending_notifications -> NotificationAgent (authorized delivery)

Security & Safety Invariants:
- `user_id` is NEVER accepted from LLM-proposed tool arguments; any attempt to
  supply or override `user_id` is rejected by `validate_tool_call`.
- Read-only alert inspection (`inspect_active_alerts`) is separated from
  state-mutating notification delivery (`deliver_pending_notifications`).
- All tool arguments are validated with Pydantic (`extra="forbid"`).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from healthguard.agents.monitoring_orchestrator import SUPPORTED_METRIC_TYPES
from healthguard.database.models import (
    DocumentIndexStatus,
    HealthMetric,
    MedicalDocument,
    Medication,
    MedicationReminder,
    MonitoringEvent,
)
from healthguard.orchestration.agents.medical_knowledge_agent import MedicalKnowledgeAgent
from healthguard.orchestration.agents.medication_agent import MedicationAgent
from healthguard.orchestration.agents.monitoring_agent import MonitoringAgent
from healthguard.orchestration.agents.notification_agent import NotificationAgent
from healthguard.orchestration.agents.risk_assessment_agent import RiskAssessmentAgent
from healthguard.orchestration.schemas import (
    MedicalCitation,
    MedicalKnowledgeAgentResult,
    MedicationAgentResult,
    MonitoringAgentResult,
    NotificationAgentResult,
    RiskAssessmentAgentResult,
)

logger = logging.getLogger(__name__)

AllowedToolName = Literal[
    "monitor_health_metric",
    "assess_health_risk",
    "check_medication_adherence",
    "query_medical_knowledge",
    "inspect_active_alerts",
    "deliver_pending_notifications",
]

ALLOWED_TOOLS: dict[str, dict[str, str]] = {
    "monitor_health_metric": {
        "agent_name": "MonitoringAgent",
        "description": (
            "Inspect recent physiological measurements for a specific metric_type "
            "(blood_glucose, heart_rate, blood_pressure_systolic, blood_pressure_diastolic, "
            "weight, steps, sleep_duration), detect statistical deviations, and check urgent thresholds."
        ),
    },
    "assess_health_risk": {
        "agent_name": "RiskAssessmentAgent",
        "description": (
            "Evaluate longitudinal health risk and directional trends (up to 30 readings) "
            "for a metric_type, plus optional experimental ML diabetes screening when requested."
        ),
    },
    "check_medication_adherence": {
        "agent_name": "MedicationAgent",
        "description": (
            "Evaluate active prescriptions, scheduled dose occurrences, taken/missed/overdue counts, "
            "adherence percentages, and pending medication reminders."
        ),
    },
    "query_medical_knowledge": {
        "agent_name": "MedicalKnowledgeAgent",
        "description": (
            "Search the clinical knowledge base and/or the user's uploaded PDF medical reports "
            "using RAG to answer medical or document questions with verified source citations."
        ),
    },
    "inspect_active_alerts": {
        "agent_name": "NotificationAgent",
        "description": (
            "Read-only inspection of unacknowledged monitoring events and pending medication reminders "
            "without delivering or modifying notification state."
        ),
    },
    "deliver_pending_notifications": {
        "agent_name": "NotificationAgent",
        "description": (
            "Process and deliver eligible pending in-app monitoring notifications subject to "
            "existing validation, cooldown, and duplicate-suppression policies."
        ),
    },
}

FORBIDDEN_IDENTITY_KEYS = {
    "user_id",
    "userid",
    "target_user_id",
    "owner_id",
    "patient_id",
    "account_id",
}


class ToolValidationError(Exception):
    """Raised when an LLM planner proposes an invalid, disallowed, or unsafe tool call."""


# ============================================================
# REQUEST-SCOPED TOOL & METRIC CONSTRAINTS
# ============================================================

METRIC_SCOPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("blood_glucose", ["glucose", "blood sugar", "sugar", "glycemic", "hba1c", "a1c", "fasting glucose", "diabetes"]),
    ("blood_pressure_systolic", ["systolic", "blood pressure", "bp", "hypertension"]),
    ("blood_pressure_diastolic", ["diastolic"]),
    ("heart_rate", ["heart rate", "pulse", "bpm", "tachycardia", "bradycardia", "resting heart"]),
    ("weight", ["weight", "bmi", "kilograms", "kg"]),
    ("steps", ["steps", "walking", "daily steps", "step count"]),
    ("sleep_duration", ["sleep", "hours of sleep", "sleep duration"]),
]


class RequestToolScope(BaseModel):
    """Request-scoped constraints that bound which tools and metrics the planner may invoke."""

    model_config = ConfigDict(extra="forbid")

    initial_intent: str
    primary_metric: str
    explicitly_mentioned_metrics: list[str] = Field(default_factory=list)
    allowed_metrics: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    requested_domains: list[str] = Field(default_factory=list)


def extract_requested_domains(
    user_request: str,
    initial_intent: str,
    minimal_context: dict[str, Any],
) -> list[str]:
    """
    Extract the explicitly requested health domains from the user request:
    - 'health_measurements'
    - 'medication_adherence'
    - 'medical_documents'
    """
    q = (user_request or "").lower()
    mentioned_metrics = extract_mentioned_metrics(user_request)

    asks_measurements = (
        any(
            w in q
            for w in (
                "measurement",
                "measurements",
                "reading",
                "readings",
                "vital",
                "vitals",
                "metric",
                "metrics",
                "trend",
                "assess",
            )
        )
        or bool(mentioned_metrics)
        or initial_intent == "health_assessment"
    )
    asks_medication = (
        any(
            w in q
            for w in (
                "medication",
                "medications",
                "medicine",
                "adherence",
                "dose",
                "doses",
                "pill",
                "prescription",
                "metformin",
                "lisinopril",
                "overdue",
                "missed dose",
                "reminder",
            )
        )
        or initial_intent == "medication_adherence"
    )
    asks_documents = (
        any(
            w in q
            for w in (
                "document",
                "documents",
                "report",
                "reports",
                "uploaded",
                "pdf",
                "lab report",
                "medical report",
                "clinical report",
                "guideline",
                "reference",
            )
        )
        or initial_intent in ("medical_document_question", "general_health_question")
    )

    domains: list[str] = []
    if initial_intent == "comprehensive_summary":
        if asks_measurements or (minimal_context or {}).get("total_measurements", 0) > 0:
            domains.append("health_measurements")
        if asks_medication or (minimal_context or {}).get("active_medications_count", 0) > 0:
            domains.append("medication_adherence")
        if asks_documents or (minimal_context or {}).get("uploaded_documents_count", 0) >= 0:
            domains.append("medical_documents")
    elif initial_intent in ("medical_document_question", "general_health_question"):
        domains.append("medical_documents")
    elif initial_intent == "medication_adherence":
        domains.append("medication_adherence")
        if mentioned_metrics:
            domains.append("health_measurements")
    elif initial_intent == "health_assessment":
        domains.append("health_measurements")
        if asks_medication:
            domains.append("medication_adherence")

    return domains


def evaluate_domain_coverage(
    request_scope: RequestToolScope,
    observations: list[dict[str, Any]],
    minimal_context: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate which explicitly requested domains have been addressed, are unavailable,
    failed, or remain unaddressed based on actual intermediate tool observations.
    """
    domain_status: dict[str, str] = {}
    unaddressed_domains: list[str] = []
    required_next_tools: list[str] = []

    target_metric = request_scope.primary_metric

    for domain in request_scope.requested_domains:
        if domain == "health_measurements":
            mon_obs = next(
                (
                    o
                    for o in reversed(observations)
                    if o.get("tool_name") == "monitor_health_metric"
                    and (o.get("intermediate_output") or {}).get("metric_type") == target_metric
                ),
                next(
                    (o for o in reversed(observations) if o.get("tool_name") == "monitor_health_metric"),
                    None,
                ),
            )
            if mon_obs is None:
                domain_status[domain] = "unaddressed"
                unaddressed_domains.append(domain)
                if "monitor_health_metric" not in required_next_tools:
                    required_next_tools.append("monitor_health_metric")
            elif mon_obs.get("status") == "failed":
                domain_status[domain] = "failed"
            else:
                mon_inter = mon_obs.get("intermediate_output") or {}
                readings_cnt = int(mon_inter.get("recent_readings_count", 0))
                if readings_cnt == 0:
                    domain_status[domain] = "unavailable"
                else:
                    risk_obs = next(
                        (o for o in reversed(observations) if o.get("tool_name") == "assess_health_risk"),
                        None,
                    )
                    if (
                        readings_cnt >= 2
                        and "assess_health_risk" in request_scope.allowed_tools
                        and risk_obs is None
                    ):
                        domain_status[domain] = "partially_addressed_needs_risk"
                        unaddressed_domains.append(domain)
                        if "assess_health_risk" not in required_next_tools:
                            required_next_tools.append("assess_health_risk")
                    else:
                        domain_status[domain] = "addressed"

        elif domain == "medication_adherence":
            med_obs = next(
                (o for o in reversed(observations) if o.get("tool_name") == "check_medication_adherence"),
                None,
            )
            if med_obs is None:
                domain_status[domain] = "unaddressed"
                unaddressed_domains.append(domain)
                if "check_medication_adherence" not in required_next_tools:
                    required_next_tools.append("check_medication_adherence")
            elif med_obs.get("status") == "failed":
                domain_status[domain] = "failed"
            else:
                med_inter = med_obs.get("intermediate_output") or {}
                if int(med_inter.get("active_medications_count", 0)) == 0:
                    domain_status[domain] = "unavailable"
                else:
                    domain_status[domain] = "addressed"

        elif domain == "medical_documents":
            know_obs = next(
                (o for o in reversed(observations) if o.get("tool_name") == "query_medical_knowledge"),
                None,
            )
            if know_obs is None:
                domain_status[domain] = "unaddressed"
                unaddressed_domains.append(domain)
                if "query_medical_knowledge" not in required_next_tools:
                    required_next_tools.append("query_medical_knowledge")
            elif know_obs.get("status") == "failed":
                domain_status[domain] = "failed"
            else:
                know_inter = know_obs.get("intermediate_output") or {}
                citations_cnt = int(know_inter.get("citations_count", 0))
                if citations_cnt == 0 and int((minimal_context or {}).get("uploaded_documents_count", 0)) == 0:
                    domain_status[domain] = "unavailable"
                else:
                    domain_status[domain] = "addressed"

    return {
        "requested_domains": list(request_scope.requested_domains),
        "domain_status": domain_status,
        "unaddressed_domains": unaddressed_domains,
        "required_next_tools": required_next_tools,
        "completed_domains": [d for d, s in domain_status.items() if s == "addressed"],
        "unavailable_domains": [d for d, s in domain_status.items() if s == "unavailable"],
        "failed_domains": [d for d, s in domain_status.items() if s == "failed"],
    }


def extract_mentioned_metrics(user_request: str) -> list[str]:
    """Return all supported metric types explicitly referenced in the user's request text."""
    q = (user_request or "").lower()
    mentioned: list[str] = []
    for metric_type, keywords in METRIC_SCOPE_KEYWORDS:
        if any(kw in q for kw in keywords):
            if metric_type not in mentioned:
                mentioned.append(metric_type)

    # If generic "blood pressure" or "bp" was mentioned without specifying only systolic,
    # allow both systolic and diastolic blood pressure.
    if (
        "blood_pressure_systolic" in mentioned
        and "blood_pressure_diastolic" not in mentioned
        and ("blood pressure" in q or re.search(r"\bbp\b", q))
        and "systolic" not in q
    ):
        mentioned.append("blood_pressure_diastolic")

    return mentioned


def build_request_tool_scope(
    user_request: str,
    initial_intent: str,
    minimal_context: dict[str, Any],
    preferred_metric: Optional[str] = None,
    allow_notification_delivery: bool = False,
) -> RequestToolScope:
    """
    Build request-scoped constraints for the planner based on the initial user intent
    and explicitly mentioned metrics.

    For example, a blood-glucose-specific health assessment is strictly scoped to
    `allowed_metrics=["blood_glucose"]` and cannot expand into unrelated blood-pressure
    or heart-rate monitoring calls.
    """
    q = (user_request or "").lower()
    mentioned = extract_mentioned_metrics(user_request)

    valid_metrics = {m for m, _ in METRIC_SCOPE_KEYWORDS}
    if mentioned:
        primary_metric = mentioned[0]
    elif preferred_metric and preferred_metric in valid_metrics:
        primary_metric = preferred_metric
    else:
        avail = (minimal_context or {}).get("available_metrics") or {}
        primary_metric = "blood_glucose"
        for candidate in (
            "blood_glucose",
            "heart_rate",
            "blood_pressure_systolic",
            "steps",
            "weight",
            "sleep_duration",
        ):
            if avail.get(candidate, 0) > 0:
                primary_metric = candidate
                break

    if mentioned:
        allowed_metrics = list(mentioned)
    else:
        allowed_metrics = [primary_metric]

    asks_medication = any(
        w in q
        for w in (
            "medication",
            "medicine",
            "adherence",
            "dose",
            "doses",
            "pill",
            "prescription",
            "metformin",
            "overdue",
            "missed dose",
            "reminder",
        )
    )
    asks_alerts = any(w in q for w in ("alert", "notification", "unread event", "active alert"))
    asks_knowledge = any(
        w in q
        for w in (
            "explain",
            "why",
            "guideline",
            "reference",
            "document",
            "report",
            "pdf",
            "what is",
            "what does",
            "meaning",
            "knowledge",
        )
    )

    if initial_intent == "health_assessment":
        allowed_tools = [
            "monitor_health_metric",
            "assess_health_risk",
            "query_medical_knowledge",
        ]
        if asks_medication:
            allowed_tools.append("check_medication_adherence")
        if asks_alerts:
            allowed_tools.append("inspect_active_alerts")
        if allow_notification_delivery:
            allowed_tools.append("deliver_pending_notifications")

    elif initial_intent in ("medical_document_question", "general_health_question"):
        allowed_tools = ["query_medical_knowledge"]
        if mentioned:
            allowed_tools.extend(["monitor_health_metric", "assess_health_risk"])
        if asks_medication:
            allowed_tools.append("check_medication_adherence")

    elif initial_intent == "medication_adherence":
        allowed_tools = ["check_medication_adherence"]
        if mentioned:
            allowed_tools.extend(["monitor_health_metric", "assess_health_risk"])
        if asks_knowledge:
            allowed_tools.append("query_medical_knowledge")

    elif initial_intent == "alert_inspection":
        allowed_tools = ["inspect_active_alerts"]
        if allow_notification_delivery:
            allowed_tools.append("deliver_pending_notifications")

    else:  # comprehensive_summary
        allowed_tools = [
            "monitor_health_metric",
            "assess_health_risk",
            "check_medication_adherence",
            "query_medical_knowledge",
            "inspect_active_alerts",
        ]
        if allow_notification_delivery:
            allowed_tools.append("deliver_pending_notifications")

    requested_domains = extract_requested_domains(
        user_request=user_request,
        initial_intent=initial_intent,
        minimal_context=minimal_context,
    )

    return RequestToolScope(
        initial_intent=initial_intent,
        primary_metric=primary_metric,
        explicitly_mentioned_metrics=mentioned,
        allowed_metrics=allowed_metrics,
        allowed_tools=allowed_tools,
        requested_domains=requested_domains,
    )


def validate_tool_against_request_scope(
    tool_name: str,
    validated_args: dict[str, Any],
    request_scope: Optional[RequestToolScope],
    observations: Optional[list[dict[str, Any]]] = None,
) -> None:
    """
    Enforce request-scoped tool and metric constraints so the planner cannot
    expand into unrelated metrics or tools not warranted by the user request.
    """
    if request_scope is None:
        return

    if tool_name not in request_scope.allowed_tools:
        raise ToolValidationError(
            f"Out-of-scope tool '{tool_name}' rejected for intent '{request_scope.initial_intent}'. "
            f"Allowed tools for this request: {request_scope.allowed_tools}."
        )

    if tool_name in ("monitor_health_metric", "assess_health_risk"):
        metric_type = validated_args.get("metric_type")
        if request_scope.allowed_metrics and metric_type not in request_scope.allowed_metrics:
            raise ToolValidationError(
                f"Out-of-scope metric '{metric_type}' rejected for '{tool_name}': "
                f"user request is scoped to {request_scope.allowed_metrics}."
            )

    if observations:
        if tool_name == "query_medical_knowledge":
            already_queried = any(
                obs.get("tool_name") == "query_medical_knowledge"
                and obs.get("status") in ("success", "degraded", "completed")
                for obs in observations
            )
            if already_queried:
                raise ToolValidationError(
                    "Tool 'query_medical_knowledge' has already been executed in this workflow; "
                    "select 'finish' instead of querying medical knowledge again."
                )

        if tool_name == "assess_health_risk":
            target_m = validated_args.get("metric_type")
            mon_obs = next(
                (
                    obs
                    for obs in reversed(observations)
                    if obs.get("tool_name") == "monitor_health_metric"
                    and (obs.get("intermediate_output") or {}).get("metric_type") == target_m
                ),
                None,
            )
            if mon_obs is not None:
                cnt = int((mon_obs.get("intermediate_output") or {}).get("recent_readings_count", 0))
                if cnt == 0:
                    raise ToolValidationError(
                        f"Cannot execute 'assess_health_risk' for '{target_m}' because "
                        "MonitoringAgent found 0 recorded readings."
                    )


def sanitize_knowledge_query_phrasing(question: str) -> str:
    """
    Ensure queries sent to MedicalKnowledgeAgent use neutral, non-diagnostic phrasing
    and never pass internal rule-based risk categories ('low', 'moderate', 'high', 'critical' risk)
    as clinical conditions or diagnostic terms.
    """
    q = (question or "").strip()
    if not q:
        return q
    # Replace internal rule-based risk tier labels so RAG does not conflate them with clinical diagnoses
    q = re.sub(
        r"(?i)\b(diagnosed with|diagnosis of|patient has)\s+(?:a\s+)?(moderate|high|low|critical)\s+(?:rule-based\s+)?risk(?:\s+of\s+\w+|\s+assessment|\s+category|\s+level)?\b",
        "statistical deviation and elevated measurement trend",
        q,
    )
    q = re.sub(
        r"(?i)\b(moderate|high|low|critical)\s+(?:rule-based\s+)?risk(?:\s+assessment|\s+category|\s+level|\s+classification|\s+of\s+diabetes)?\b",
        "statistical deviation and elevated measurement trend",
        q,
    )
    return q[:500]


# ============================================================
# TOOL ARGUMENT SCHEMAS (extra="forbid")
# ============================================================

SupportedMetricLiteral = Literal[
    "blood_glucose",
    "heart_rate",
    "blood_pressure_systolic",
    "blood_pressure_diastolic",
    "weight",
    "steps",
    "sleep_duration",
]


class MonitorMetricArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_type: SupportedMetricLiteral = "blood_glucose"
    baseline_window: int = Field(default=5, ge=2, le=15)
    recent_window: int = Field(default=3, ge=1, le=10)


class AssessRiskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_type: SupportedMetricLiteral = "blood_glucose"
    include_experimental_ml: bool = False


class CheckMedicationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_reminders: bool = True


class QueryKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=3, max_length=500)
    include_user_documents: bool = True
    include_global_knowledge: bool = True
    n_results: int = Field(default=3, ge=1, le=6)


class InspectAlertsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=25)


class DeliverNotificationsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


TOOL_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "monitor_health_metric": MonitorMetricArgs,
    "assess_health_risk": AssessRiskArgs,
    "check_medication_adherence": CheckMedicationArgs,
    "query_medical_knowledge": QueryKnowledgeArgs,
    "inspect_active_alerts": InspectAlertsArgs,
    "deliver_pending_notifications": DeliverNotificationsArgs,
}


# ============================================================
# MINIMAL CONTEXT RETRIEVAL (PRIVACY-AWARE)
# ============================================================

def _sanitize_label(text: str, max_len: int = 80) -> str:
    """Strip control characters and prompt-injection markers from filenames/labels."""
    cleaned = re.sub(r"[\r\n\t\x00-\x1f]+", " ", str(text or "")).strip()
    cleaned = re.sub(r"(?i)(ignore\s+previous|system\s*:|assistant\s*:)", "", cleaned)
    return cleaned[:max_len]


def get_minimal_user_context(db: Session, user_id: int) -> dict[str, Any]:
    """
    Retrieve lightweight, privacy-preserving metadata about what data is available
    for the authenticated user (counts and metric types only — no raw medical notes).
    """
    metric_rows = db.execute(
        select(HealthMetric.metric_type, func.count(HealthMetric.id))
        .where(HealthMetric.user_id == user_id)
        .group_by(HealthMetric.metric_type)
    ).all()
    metric_counts = {str(m_type): int(cnt) for m_type, cnt in metric_rows}

    active_meds_count = int(
        db.scalar(
            select(func.count(Medication.id)).where(
                Medication.user_id == user_id,
                Medication.is_active.is_(True),
            )
        )
        or 0
    )

    docs = list(
        db.scalars(
            select(MedicalDocument)
            .where(MedicalDocument.user_id == user_id)
            .order_by(MedicalDocument.uploaded_at.desc())
            .limit(10)
        ).all()
    )
    indexed_docs_count = int(
        db.scalar(
            select(func.count(DocumentIndexStatus.id)).where(
                DocumentIndexStatus.user_id == user_id,
                DocumentIndexStatus.status == "indexed",
            )
        )
        or 0
    )

    unread_events_count = int(
        db.scalar(
            select(func.count(MonitoringEvent.id)).where(
                MonitoringEvent.user_id == user_id,
                MonitoringEvent.is_acknowledged.is_(False),
            )
        )
        or 0
    )

    pending_events_count = int(
        db.scalar(
            select(func.count(MonitoringEvent.id)).where(
                MonitoringEvent.user_id == user_id,
                MonitoringEvent.notification_status == "pending",
            )
        )
        or 0
    )

    pending_reminders_count = int(
        db.scalar(
            select(func.count(MedicationReminder.id)).where(
                MedicationReminder.user_id == user_id,
                MedicationReminder.status == "pending",
            )
        )
        or 0
    )

    return {
        "available_metrics": metric_counts,
        "total_measurements": sum(metric_counts.values()),
        "active_medications_count": active_meds_count,
        "uploaded_documents_count": len(docs),
        "indexed_documents_count": indexed_docs_count,
        "uploaded_document_filenames": [_sanitize_label(d.filename) for d in docs[:5]],
        "unread_monitoring_events_count": unread_events_count,
        "pending_notification_events_count": pending_events_count,
        "pending_medication_reminders_count": pending_reminders_count,
    }


# ============================================================
# VALIDATION & CANONICAL SIGNATURES
# ============================================================

def validate_tool_call(
    tool_name: str,
    raw_args: Optional[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """
    Validate a proposed tool call against the allowlist, forbidden identity overrides,
    and tool-specific Pydantic argument schema.
    """
    if not tool_name or not isinstance(tool_name, str):
        raise ToolValidationError("Tool name must be a non-empty string.")

    clean_name = tool_name.strip()
    if clean_name not in ALLOWED_TOOLS:
        raise ToolValidationError(
            f"Disallowed or unknown tool '{clean_name}'. "
            f"Allowed tools: {', '.join(sorted(ALLOWED_TOOLS.keys()))}"
        )

    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, dict):
        raise ToolValidationError("Tool arguments must be a JSON object.")

    # Never allow the LLM to specify or override user identity
    lowered_keys = {str(k).lower() for k in raw_args.keys()}
    forbidden_found = lowered_keys.intersection(FORBIDDEN_IDENTITY_KEYS)
    if forbidden_found:
        raise ToolValidationError(
            f"Security violation: LLM cannot specify identity parameter(s) {sorted(forbidden_found)}. "
            "User identity is strictly bound by backend authentication."
        )

    schema_cls = TOOL_ARG_SCHEMAS[clean_name]
    try:
        validated_model = schema_cls(**raw_args)
    except ValidationError as exc:
        raise ToolValidationError(
            f"Invalid arguments for tool '{clean_name}': {exc.errors()}"
        ) from exc

    return clean_name, validated_model.model_dump()


def canonical_tool_signature(tool_name: str, validated_args: dict[str, Any]) -> str:
    """Create a canonical signature string to detect duplicate tool invocations."""
    normalized_args = dict(validated_args)
    if "question" in normalized_args and isinstance(normalized_args["question"], str):
        normalized_args["question"] = re.sub(
            r"\s+", " ", normalized_args["question"].strip().lower()
        )
    return f"{tool_name}:{json.dumps(normalized_args, sort_keys=True)}"


# ============================================================
# TOOL EXECUTION & OBSERVATION FORMATTING
# ============================================================

class ToolExecutionOutcome(BaseModel):
    tool_name: str
    agent_name: str
    status: str
    duration_ms: int
    details: str
    intermediate_output: dict[str, Any]
    observation_text: str
    monitoring_result: Optional[MonitoringAgentResult] = None
    risk_result: Optional[RiskAssessmentAgentResult] = None
    medication_result: Optional[MedicationAgentResult] = None
    knowledge_result: Optional[MedicalKnowledgeAgentResult] = None
    notification_result: Optional[NotificationAgentResult] = None
    error_recovery: Optional[str] = None


def execute_allowlisted_tool(
    db: Session,
    user_id: int,
    tool_name: str,
    validated_args: dict[str, Any],
    monitoring_agent: MonitoringAgent,
    risk_agent: RiskAssessmentAgent,
    medication_agent: MedicationAgent,
    knowledge_agent: MedicalKnowledgeAgent,
    notification_agent: NotificationAgent,
    experimental_ml_enabled: bool = False,
    ml_features: Optional[dict[str, Any]] = None,
    allow_notification_delivery: bool = False,
) -> ToolExecutionOutcome:
    """
    Execute a validated allowlisted tool using the authenticated `user_id`
    and return a structured outcome + sanitized observation for the planner loop.
    """
    t0 = time.time()
    agent_name = ALLOWED_TOOLS[tool_name]["agent_name"]

    if tool_name == "monitor_health_metric":
        metric_type = validated_args["metric_type"]
        res = monitoring_agent.analyze_metrics(
            user_id=user_id,
            metric_type=metric_type,
            baseline_window=validated_args.get("baseline_window", 5),
            recent_window=validated_args.get("recent_window", 3),
        )
        duration_ms = int((time.time() - t0) * 1000)
        inter = {
            "metric_type": res.metric_type,
            "status": res.status,
            "latest_value": res.latest_value,
            "unit": res.unit,
            "statistical_status": res.statistical_status,
            "monitoring_priority": res.monitoring_priority,
            "is_urgent": res.is_urgent,
            "recent_readings_count": res.recent_readings_count,
        }
        obs = (
            f"Tool monitor_health_metric({metric_type}) -> status={res.status}, "
            f"latest_value={res.latest_value} {res.unit}, readings_count={res.recent_readings_count}, "
            f"statistical_status={res.statistical_status}, is_urgent={res.is_urgent}. "
            f"Summary: {res.summary}"
        )
        return ToolExecutionOutcome(
            tool_name=tool_name,
            agent_name=agent_name,
            status=res.status,
            duration_ms=duration_ms,
            details=res.summary,
            intermediate_output=inter,
            observation_text=obs,
            monitoring_result=res,
        )

    if tool_name == "assess_health_risk":
        metric_type = validated_args["metric_type"]
        use_ml = bool(experimental_ml_enabled or validated_args.get("include_experimental_ml"))
        res = risk_agent.evaluate_risk(
            user_id=user_id,
            metric_type=metric_type,
            experimental_ml=use_ml,
            ml_features=ml_features if use_ml else None,
        )
        duration_ms = int((time.time() - t0) * 1000)
        primary_finding = res.rule_based_findings[0] if res.rule_based_findings else {}
        inter = {
            "metric_type": metric_type,
            "risk_level": res.risk_level.value,
            "direction": primary_finding.get("direction"),
            "mean": primary_finding.get("mean"),
            "latest": primary_finding.get("latest"),
            "unit": primary_finding.get("unit"),
            "sample_size": primary_finding.get("sample_size"),
            "rule_findings_count": len(res.rule_based_findings),
            "experimental_ml_included": res.is_experimental,
            "summary": res.summary,
        }
        obs = (
            f"Tool assess_health_risk({metric_type}) -> rule_based_risk_category={res.risk_level.value}, "
            f"direction={primary_finding.get('direction')}, mean={primary_finding.get('mean')} {primary_finding.get('unit') or ''}, "
            f"rule_findings={len(res.rule_based_findings)}, experimental_ml={res.is_experimental}. "
            f"Summary: {res.summary}"
        )
        return ToolExecutionOutcome(
            tool_name=tool_name,
            agent_name=agent_name,
            status=res.risk_level.value,
            duration_ms=duration_ms,
            details=res.summary,
            intermediate_output=inter,
            observation_text=obs,
            risk_result=res,
        )

    if tool_name == "check_medication_adherence":
        if validated_args.get("refresh_reminders", True):
            from healthguard.services.medication_reminder_service import generate_reminders_for_user
            try:
                generate_reminders_for_user(db, user_id)
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("Medication reminder refresh note: %s", exc)

        res = medication_agent.evaluate_medications(user_id=user_id)
        duration_ms = int((time.time() - t0) * 1000)
        inter = {
            "active_medications_count": res.active_medications_count,
            "overall_adherence_percentage": res.overall_adherence_percentage,
            "taken_doses_count": res.taken_doses_count,
            "missed_doses_count": res.missed_doses_count,
            "overdue_doses_count": res.overdue_doses_count,
            "pending_reminders_count": len(res.pending_reminders),
        }
        obs = (
            f"Tool check_medication_adherence() -> active_medications={res.active_medications_count}, "
            f"adherence_pct={res.overall_adherence_percentage}, taken={res.taken_doses_count}, "
            f"missed={res.missed_doses_count}, overdue={res.overdue_doses_count}, "
            f"pending_reminders={len(res.pending_reminders)}. Summary: {res.summary}"
        )
        return ToolExecutionOutcome(
            tool_name=tool_name,
            agent_name=agent_name,
            status="completed" if res.active_medications_count > 0 else "insufficient_data",
            duration_ms=duration_ms,
            details=res.summary,
            intermediate_output=inter,
            observation_text=obs,
            medication_result=res,
        )

    if tool_name == "query_medical_knowledge":
        raw_question = validated_args["question"]
        question = sanitize_knowledge_query_phrasing(raw_question)
        include_user_docs = bool(validated_args.get("include_user_documents", True))

        user_docs: list[MedicalDocument] = []
        if include_user_docs:
            user_docs = list(
                db.scalars(
                    select(MedicalDocument)
                    .where(MedicalDocument.user_id == user_id)
                    .order_by(MedicalDocument.uploaded_at.desc())
                    .limit(3)
                ).all()
            )
            if user_docs and not any(
                marker in question.lower()
                for marker in ("uploaded", "my report", "my document", "my lab", "my file")
            ):
                question = f"{question.rstrip('.')} (including findings from my uploaded medical report)."
                question = question[:500]

        res = knowledge_agent.query_knowledge(
            user_id=user_id,
            question=question,
            n_results=validated_args.get("n_results", 3),
            include_user_documents=include_user_docs,
            include_global_knowledge=validated_args.get("include_global_knowledge", True),
            max_tokens=280,
        )

        # Ensure uploaded user medical documents in SQLite are represented when include_user_documents=True
        if include_user_docs and user_docs:
            existing_titles = {(c.title or "").lower() for c in res.citations}
            added_doc_notes: list[str] = []
            for udoc in user_docs:
                fname = _sanitize_label(udoc.filename, 80)
                excerpt_text = (udoc.extracted_text or "").strip()
                if fname.lower() not in existing_titles and excerpt_text:
                    res.citations.insert(
                        0,
                        MedicalCitation(
                            title=fname,
                            source_organization="Uploaded Medical Report",
                            source_url=None,
                            excerpt=excerpt_text[:300],
                        ),
                    )
                    existing_titles.add(fname.lower())
                    added_doc_notes.append(f"Uploaded report '{fname}': {excerpt_text[:220]}")
            if added_doc_notes and not any(ud.filename.lower() in (res.explanation or "").lower() for ud in user_docs):
                res.explanation = (
                    f"Uploaded Medical Document Findings ({'; '.join(added_doc_notes)}). "
                    f"{res.explanation}"
                )

        duration_ms = int((time.time() - t0) * 1000)
        citation_titles = [_sanitize_label(c.title, 60) for c in res.citations[:5]]
        inter = {
            "status": res.status,
            "query": _sanitize_label(question, 120),
            "citations_count": len(res.citations),
            "citation_titles": citation_titles,
            "uploaded_documents_found": len(user_docs),
            "limitations": res.limitations,
            "is_emergency": res.is_emergency,
            "rag_generation_ms": duration_ms,
        }
        obs = (
            f"Tool query_medical_knowledge() -> status={res.status}, "
            f"citations_count={len(res.citations)} ({', '.join(citation_titles) or 'none'}), "
            f"uploaded_documents_found={len(user_docs)}, "
            f"is_emergency={res.is_emergency}. "
            f"Answer preview: {_sanitize_label(res.explanation, 220)}"
        )
        return ToolExecutionOutcome(
            tool_name=tool_name,
            agent_name=agent_name,
            status=res.status,
            duration_ms=duration_ms,
            details=f"Retrieved {len(res.citations)} citation(s) ({res.status}).",
            intermediate_output=inter,
            observation_text=obs,
            knowledge_result=res,
        )

    if tool_name == "inspect_active_alerts":
        limit = validated_args.get("limit", 10)
        events = list(
            db.scalars(
                select(MonitoringEvent)
                .where(
                    MonitoringEvent.user_id == user_id,
                    MonitoringEvent.is_acknowledged.is_(False),
                )
                .order_by(MonitoringEvent.created_at.desc())
                .limit(limit)
            ).all()
        )
        reminders = list(
            db.scalars(
                select(MedicationReminder)
                .where(
                    MedicationReminder.user_id == user_id,
                    MedicationReminder.status == "pending",
                )
                .order_by(MedicationReminder.created_at.desc())
                .limit(limit)
            ).all()
        )
        duration_ms = int((time.time() - t0) * 1000)
        summary_str = (
            f"Read-only alert inspection: {len(events)} unacknowledged monitoring event(s), "
            f"{len(reminders)} pending medication reminder(s)."
        )
        notif_res = NotificationAgentResult(
            notifications_created=[
                {
                    "event_id": ev.id,
                    "metric_type": ev.metric_type,
                    "event_level": ev.event_level,
                    "message": ev.message,
                    "status": ev.notification_status,
                }
                for ev in events
            ],
            suppressed_count=0,
            summary=summary_str,
        )
        inter = {
            "mode": "read_only_inspection",
            "unread_monitoring_events_count": len(events),
            "pending_medication_reminders_count": len(reminders),
        }
        obs = (
            f"Tool inspect_active_alerts() -> unread_events={len(events)}, "
            f"pending_reminders={len(reminders)}. {summary_str}"
        )
        return ToolExecutionOutcome(
            tool_name=tool_name,
            agent_name=agent_name,
            status="completed",
            duration_ms=duration_ms,
            details=summary_str,
            intermediate_output=inter,
            observation_text=obs,
            notification_result=notif_res,
        )

    if tool_name == "deliver_pending_notifications":
        if not allow_notification_delivery:
            # Fall back safely to read-only inspection when delivery is not authorized
            duration_ms = int((time.time() - t0) * 1000)
            summary_str = (
                "Notification delivery skipped (read-only mode active; "
                "set allow_notification_delivery=True to authorize delivery)."
            )
            notif_res = NotificationAgentResult(
                notifications_created=[],
                suppressed_count=0,
                summary=summary_str,
            )
            return ToolExecutionOutcome(
                tool_name=tool_name,
                agent_name=agent_name,
                status="skipped",
                duration_ms=duration_ms,
                details=summary_str,
                intermediate_output={"authorized": False, "delivered_count": 0},
                observation_text=f"Tool deliver_pending_notifications() -> {summary_str}",
                notification_result=notif_res,
                error_recovery="Restricted to non-mutating mode because notification delivery was not explicitly authorized.",
            )

        res = notification_agent.process_pending_alerts(user_id=user_id)
        duration_ms = int((time.time() - t0) * 1000)
        inter = {
            "mode": "authorized_delivery",
            "delivered_count": len(res.notifications_created),
            "suppressed_count": res.suppressed_count,
            "summary": res.summary,
        }
        obs = (
            f"Tool deliver_pending_notifications() -> delivered={len(res.notifications_created)}, "
            f"suppressed={res.suppressed_count}. Summary: {res.summary}"
        )
        return ToolExecutionOutcome(
            tool_name=tool_name,
            agent_name=agent_name,
            status="completed",
            duration_ms=duration_ms,
            details=res.summary,
            intermediate_output=inter,
            observation_text=obs,
            notification_result=res,
        )

    raise ToolValidationError(f"Unhandled allowlisted tool: {tool_name}")

