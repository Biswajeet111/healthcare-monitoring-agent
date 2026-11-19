"""
Bounded Iterative Planner — Dynamic Agentic Orchestration

Implements the decision step of the iterative Decision -> Execution -> Observation loop:
1. Examines the authenticated user's request, minimal privacy-preserving context,
   and sanitized observations from tools already executed in the current run.
2. Uses Ollama (`llama3.1`) in structured JSON mode with bounded retries to propose
   either the next single allowlisted tool call or `"finish"`.
3. Validates every LLM proposal against `PlannerDecision`, the tool allowlist,
   Pydantic argument schemas (`extra="forbid"`), identity-override checks, and
   duplicate-signature prevention.
4. When Ollama is unavailable or returns invalid proposals after bounded retries,
   provides a clearly labeled step-by-step deterministic fallback (`planner_mode="deterministic_fallback"`)
   that still adapts its next decision to actual intermediate tool outputs.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from healthguard.core.config import settings
from healthguard.orchestration.tools import (
    ALLOWED_TOOLS,
    RequestToolScope,
    ToolValidationError,
    build_request_tool_scope,
    canonical_tool_signature,
    evaluate_domain_coverage,
    validate_tool_against_request_scope,
    validate_tool_call,
)
from healthguard.rag.llm_service import (
    _strip_think_tags,
    check_groq_available,
    check_ollama_available,
    get_active_llm_model,
    get_active_llm_provider,
)

logger = logging.getLogger(__name__)

PLANNER_TIMEOUT_SECONDS = 20.0
MAX_PLANNER_RETRIES = 2

PlannerIntent = Literal[
    "medical_document_question",
    "health_assessment",
    "medication_adherence",
    "comprehensive_summary",
    "alert_inspection",
    "insufficient_information",
    "general_health_question",
]


class PlannerDecision(BaseModel):
    """Schema-validated single-step decision from the planner."""

    model_config = ConfigDict(extra="ignore")

    detected_intent: PlannerIntent = "general_health_question"
    action: Literal["call_tool", "finish"]
    tool_name: Optional[str] = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    selection_reason: str = Field(
        default="Selected based on user request and available health context.",
        min_length=3,
        max_length=400,
    )
    final_guidance: Optional[str] = None


class ValidatedPlannerStep(BaseModel):
    """Validated planner output ready for orchestrator execution."""

    decision: PlannerDecision
    planner_mode: Literal["llm_assisted", "deterministic_fallback"]
    rejection_notes: list[str] = Field(default_factory=list)
    planner_llm_ms: int = 0


PLANNER_SYSTEM_PROMPT = """You are the bounded agentic planner for HealthGuard AI, an educational healthcare monitoring platform.
Your job is to operate in an iterative Decision -> Execution -> Observation loop.
At each step, inspect:
1. USER_REQUEST and LOCKED_REQUEST_INTENT
2. ALLOWED_METRICS_FOR_THIS_REQUEST and ALLOWED_TOOLS_FOR_THIS_REQUEST
3. MINIMAL_USER_CONTEXT
4. COMPLETED_STEPS (tools already called and their actual observations)
5. ALREADY_EXECUTED_SIGNATURES (never repeat a signature in this list)

You must return ONLY a single valid JSON object matching this exact schema:
{
  "detected_intent": "medical_document_question" | "health_assessment" | "medication_adherence" | "comprehensive_summary" | "alert_inspection" | "insufficient_information" | "general_health_question",
  "action": "call_tool" | "finish",
  "tool_name": "<one allowlisted tool name when action is call_tool, or null when action is finish>",
  "tool_args": { ... },
  "selection_reason": "<concise 1-sentence user-readable reason explaining why this next step or finish was chosen>",
  "final_guidance": "<optional concise synthesis note when action is finish, or null>"
}

ALLOWLISTED TOOLS & EXACT ARGUMENTS:
1. "monitor_health_metric":
   - Args: {"metric_type": "<must be in ALLOWED_METRICS_FOR_THIS_REQUEST>"}
   - Use to inspect recent readings, detect statistical deviations, and check urgent thresholds.
2. "assess_health_risk":
   - Args: {"metric_type": "<must be in ALLOWED_METRICS_FOR_THIS_REQUEST>", "include_experimental_ml": boolean}
   - Use AFTER monitor_health_metric when recent_readings_count >= 2 to evaluate directional trends and rule-based risk category.
3. "check_medication_adherence":
   - Args: {"refresh_reminders": true}
   - Use when the user asks about medications, doses, adherence, reminders, or a comprehensive summary.
4. "query_medical_knowledge":
   - Args: {"question": "<3..300 char neutral educational query>", "include_user_documents": boolean, "include_global_knowledge": boolean, "n_results": 3}
   - Use for uploaded medical report questions, clinical guidelines, or when a monitoring statistical deviation/elevated risk warrants grounded medical explanation.
   - Use neutral, non-diagnostic phrasing in "question". Never pass internal rule-based risk categories ("moderate", "high") as confirmed clinical diagnoses.
5. "inspect_active_alerts":
   - Args: {"limit": 10}
   - Read-only inspection of unacknowledged monitoring events and pending medication reminders.
6. "deliver_pending_notifications":
   - Args: {}
   - Only use when notification delivery is authorized and pending events exist.

STRICT PLANNING & SAFETY RULES:
- NEVER include "user_id" or any patient identifier in tool_args.
- Keep "detected_intent" equal to LOCKED_REQUEST_INTENT (unless recent_readings_count == 0 for the requested resource, in which case use "insufficient_information" and "finish").
- NEVER select any tool listed in ALREADY_COMPLETED_TOOLS_DO_NOT_CALL_AGAIN.
- Always select your next "tool_name" from NEXT_REQUIRED_TOOLS_TO_CHOOSE_FROM (or ALLOWED_TOOLS_FOR_THIS_REQUEST) and your "metric_type" from ALLOWED_METRICS_FOR_THIS_REQUEST.
  * For a blood_glucose assessment, NEVER call monitor_health_metric or assess_health_risk on blood_pressure_systolic, blood_pressure_diastolic, or heart_rate.
  * When "monitor_health_metric" is already in ALREADY_COMPLETED_TOOLS_DO_NOT_CALL_AGAIN, do NOT call "monitor_health_metric" again; instead select "assess_health_risk", "check_medication_adherence", or "query_medical_knowledge" from NEXT_REQUIRED_TOOLS_TO_CHOOSE_FROM.
- Inspect UNADDRESSED_REQUESTED_DOMAINS and NEXT_REQUIRED_TOOLS_TO_CHOOSE_FROM:
  * NEVER return action="finish" while UNADDRESSED_REQUESTED_DOMAINS is non-empty.
  * For a comprehensive summary requesting health measurements, medication adherence, and uploaded medical reports, you MUST ensure monitor_health_metric, assess_health_risk (when readings >= 2), check_medication_adherence, and query_medical_knowledge are all executed before returning action="finish".
- Once all requested domains have been addressed, immediately return action="finish".
- Never repeat a tool call with the same arguments.
- Never diagnose conditions, prescribe medications, or recommend dosage changes.
"""


# ============================================================
# INTENT & METRIC DETECTION HELPERS
# ============================================================

METRIC_KEYWORDS: list[tuple[str, list[str]]] = [
    ("blood_glucose", ["glucose", "blood sugar", "sugar", "glycemic", "hba1c", "a1c", "fasting glucose", "diabetes"]),
    ("blood_pressure_systolic", ["systolic", "blood pressure", "bp", "hypertension", "pressure"]),
    ("blood_pressure_diastolic", ["diastolic"]),
    ("heart_rate", ["heart rate", "pulse", "bpm", "tachycardia", "bradycardia", "resting heart"]),
    ("weight", ["weight", "bmi", "kilograms", "kg"]),
    ("steps", ["steps", "walking", "daily steps", "activity", "step count"]),
    ("sleep_duration", ["sleep", "hours of sleep", "sleep duration", "rest"]),
]


def infer_target_metric(
    user_request: str,
    minimal_context: dict[str, Any],
    preferred_metric: Optional[str] = None,
) -> str:
    """Infer the most relevant supported metric from the user request or available context."""
    q = (user_request or "").lower()
    for metric_type, keywords in METRIC_KEYWORDS:
        if any(kw in q for kw in keywords):
            return metric_type

    if preferred_metric and preferred_metric in {m for m, _ in METRIC_KEYWORDS}:
        return preferred_metric

    avail = minimal_context.get("available_metrics") or {}
    for candidate in ("blood_glucose", "heart_rate", "blood_pressure_systolic", "steps", "weight", "sleep_duration"):
        if avail.get(candidate, 0) > 0:
            return candidate

    return preferred_metric or "blood_glucose"


def classify_request_intent(user_request: str) -> PlannerIntent:
    """Classify the primary intent of a user request."""
    q = (user_request or "").lower()

    # Comprehensive summary keywords
    if any(
        phrase in q
        for phrase in (
            "comprehensive",
            "full summary",
            "overall health",
            "complete health summary",
            "everything",
            "all my health",
            "overall summary",
            "personalized health summary",
            "health overview",
        )
    ):
        return "comprehensive_summary"

    # Uploaded document / lab report / medical knowledge question
    doc_markers = (
        "document",
        "uploaded",
        "pdf",
        "lab report",
        "laboratory report",
        "clinical report",
        "medical report",
        "what does my report",
        "in my report",
        "reference guideline",
        "clinical guideline",
    )
    med_markers = (
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
        "schedule",
    )
    metric_markers = (
        "assess",
        "assessment",
        "trend",
        "readings",
        "measurements",
        "statistical deviation",
        "deviation",
        "monitor",
        "monitoring",
        "check my glucose",
        "check my blood",
        "check my heart",
        "evaluate my",
        "recent glucose",
        "recent blood pressure",
        "recent heart rate",
    )
    alert_markers = (
        "alert",
        "notification",
        "unread event",
        "active alert",
    )

    has_doc = any(m in q for m in doc_markers)
    has_med = any(m in q for m in med_markers)
    has_metric = any(m in q for m in metric_markers) or any(
        any(kw in q for kw in kws) for _, kws in METRIC_KEYWORDS
    )
    has_alert = any(m in q for m in alert_markers)

    # Multi-domain requests combining measurements, medications, and documents (or asking for a summary across multiple domains)
    if (has_metric and has_med and has_doc) or (
        "summary" in q and sum([bool(has_metric), bool(has_med), bool(has_doc)]) >= 2
    ):
        return "comprehensive_summary"

    if has_doc and not ("assess" in q and "report" not in q and "document" not in q and "pdf" not in q):
        if not ("adherence" in q or "missed dose" in q):
            return "medical_document_question"
    if has_med and not has_doc and not ("assess" in q and has_metric and "medication" not in q):
        if "adherence" in q or "dose" in q or "medication" in q or "prescription" in q or "pill" in q:
            return "medication_adherence"
    if has_alert and not has_metric and not has_med:
        return "alert_inspection"
    if has_metric:
        # Distinguish a pure conceptual question ("What is normal blood glucose according to guidelines?")
        # from a personal measurement assessment ("Assess my recent blood glucose measurements and explain...")
        personal_pronouns = (
            "my ",
            "mine",
            "i have",
            "recent",
            "assess",
            "assessment",
            "evaluate",
            "check",
            "trend",
            "readings",
            "measurements",
            "statistical deviation",
            "deviation",
        )
        explicit_doc_ref = any(
            d in q for d in ("my report", "lab report", "uploaded", "pdf", "in my report", "document")
        )
        if explicit_doc_ref:
            return "medical_document_question"
        if any(p in q for p in personal_pronouns):
            return "health_assessment"
        if has_doc or ("what is" in q or "guideline" in q or "explain" in q):
            return "medical_document_question"
        return "health_assessment"
    if has_doc:
        return "medical_document_question"
    if has_med:
        return "medication_adherence"

    return "general_health_question"


# ============================================================
# OLLAMA JSON PLANNER (WITH BOUNDED RETRIES)
# ============================================================

def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Extract and parse a JSON object from an LLM response string."""
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("LLM response did not contain a valid JSON object.")


def _build_planner_user_payload(
    user_request: str,
    minimal_context: dict[str, Any],
    observations: list[dict[str, Any]],
    executed_signatures: set[str],
    preferred_metric: Optional[str],
    allow_notification_delivery: bool,
    retry_feedback: Optional[str] = None,
    request_scope: Optional[RequestToolScope] = None,
) -> dict[str, Any]:
    """Build the compact JSON planning payload shared by Ollama and Groq planners."""
    if request_scope is None:
        initial_intent = classify_request_intent(user_request)
        request_scope = build_request_tool_scope(
            user_request=user_request,
            initial_intent=initial_intent,
            minimal_context=minimal_context,
            preferred_metric=preferred_metric,
            allow_notification_delivery=allow_notification_delivery,
        )
    scoped_context = dict(minimal_context or {})
    if request_scope and request_scope.initial_intent != "comprehensive_summary" and request_scope.allowed_metrics:
        raw_avail = scoped_context.get("available_metrics") or {}
        scoped_context["available_metrics"] = {
            k: v for k, v in raw_avail.items() if k in request_scope.allowed_metrics
        }

    executed_tool_names = {obs.get("tool_name") for obs in observations}
    monitored_metrics = {
        (obs.get("intermediate_output") or {}).get("metric_type")
        for obs in observations
        if obs.get("tool_name") == "monitor_health_metric"
    }
    risk_assessed_metrics = {
        (obs.get("intermediate_output") or {}).get("metric_type")
        for obs in observations
        if obs.get("tool_name") == "assess_health_risk"
    }
    remaining_tools: list[str] = []
    if request_scope:
        for t in request_scope.allowed_tools:
            if t == "monitor_health_metric" and all(m in monitored_metrics for m in request_scope.allowed_metrics):
                continue
            if t == "assess_health_risk" and all(m in risk_assessed_metrics for m in request_scope.allowed_metrics):
                continue
            if t in ("query_medical_knowledge", "check_medication_adherence", "inspect_active_alerts", "deliver_pending_notifications") and t in executed_tool_names:
                continue
            remaining_tools.append(t)
    else:
        remaining_tools = list(ALLOWED_TOOLS.keys())

    coverage = evaluate_domain_coverage(request_scope, observations, minimal_context)
    next_required_tools = coverage["required_next_tools"] or remaining_tools

    user_payload: dict[str, Any] = {
        "user_request": user_request,
        "locked_request_intent": request_scope.initial_intent if request_scope else classify_request_intent(user_request),
        "already_completed_tools_do_not_call_again": sorted(str(t) for t in executed_tool_names if t),
        "next_required_tools_to_choose_from": next_required_tools,
        "unaddressed_requested_domains": coverage["unaddressed_domains"],
        "domain_coverage_status": coverage["domain_status"],
        "requested_domains": coverage["requested_domains"],
        "primary_metric": request_scope.primary_metric if request_scope else preferred_metric,
        "allowed_metrics_for_this_request": request_scope.allowed_metrics if request_scope else [],
        "allowed_tools_for_this_request": remaining_tools,
        "allow_notification_delivery": allow_notification_delivery,
        "minimal_user_context": scoped_context,
        "completed_steps": [
            {
                "step": obs.get("step"),
                "tool_name": obs.get("tool_name"),
                "status": obs.get("status"),
                "observation": obs.get("observation"),
            }
            for obs in observations
        ],
        "already_executed_signatures": sorted(executed_signatures),
    }
    if retry_feedback:
        user_payload["previous_invalid_proposal_error"] = retry_feedback
    return user_payload


def _call_ollama_planner_once(
    user_request: str,
    minimal_context: dict[str, Any],
    observations: list[dict[str, Any]],
    executed_signatures: set[str],
    preferred_metric: Optional[str],
    allow_notification_delivery: bool,
    retry_feedback: Optional[str] = None,
    request_scope: Optional[RequestToolScope] = None,
) -> PlannerDecision:
    """Invoke Ollama once for the current step of the planning loop."""
    user_payload = _build_planner_user_payload(
        user_request=user_request,
        minimal_context=minimal_context,
        observations=observations,
        executed_signatures=executed_signatures,
        preferred_metric=preferred_metric,
        allow_notification_delivery=allow_notification_delivery,
        retry_feedback=retry_feedback,
        request_scope=request_scope,
    )

    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, indent=2)},
        ],
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 160,
        },
    }

    response = httpx.post(
        f"{settings.OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=PLANNER_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    raw_content = data.get("message", {}).get("content", "")
    parsed_json = _extract_json_object(raw_content)
    return PlannerDecision(**parsed_json)


def _call_groq_planner_once(
    user_request: str,
    minimal_context: dict[str, Any],
    observations: list[dict[str, Any]],
    executed_signatures: set[str],
    preferred_metric: Optional[str],
    allow_notification_delivery: bool,
    retry_feedback: Optional[str] = None,
    request_scope: Optional[RequestToolScope] = None,
) -> PlannerDecision:
    """Invoke Groq cloud inference once in strict JSON mode for the current planning step."""
    api_key = (settings.GROQ_API_KEY or "").strip()
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured for cloud planning.")

    user_payload = _build_planner_user_payload(
        user_request=user_request,
        minimal_context=minimal_context,
        observations=observations,
        executed_signatures=executed_signatures,
        preferred_metric=preferred_metric,
        allow_notification_delivery=allow_notification_delivery,
        retry_feedback=retry_feedback,
        request_scope=request_scope,
    )

    base_url = settings.GROQ_BASE_URL.rstrip("/")
    payload = {
        "model": get_active_llm_model(),
        "messages": [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, indent=2)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 400,
    }

    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=PLANNER_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    raw_content = (
        choices[0].get("message", {}).get("content", "")
        if choices and isinstance(choices[0], dict)
        else ""
    )
    parsed_json = _extract_json_object(_strip_think_tags(raw_content))
    return PlannerDecision(**parsed_json)


def evaluate_execution_sufficiency(
    user_request: str,
    minimal_context: dict[str, Any],
    observations: list[dict[str, Any]],
    request_scope: RequestToolScope,
    allow_notification_delivery: bool = False,
) -> Optional[PlannerDecision]:
    """
    Determine whether the already-executed tools and observations have sufficiently
    addressed the user's request within its locked intent and metric scope.

    Returns a `PlannerDecision(action="finish", ...)` with an accurate termination reason
    when sufficient evidence has been gathered, or `None` if further tool execution is needed.
    """
    if not observations:
        return None

    intent: PlannerIntent = request_scope.initial_intent  # type: ignore[assignment]
    target_metric = request_scope.primary_metric
    q_lower = (user_request or "").lower()
    executed_tools = [str(obs.get("tool_name") or "") for obs in observations]

    executed_agent_names: list[str] = []
    for t_name in executed_tools:
        a_name = ALLOWED_TOOLS.get(t_name, {}).get("agent_name")
        if a_name and a_name not in executed_agent_names:
            executed_agent_names.append(a_name)
    agents_str = ", ".join(executed_agent_names) if executed_agent_names else "selected agents"

    # 1. Medical Document / General Clinical Knowledge Question
    if intent in ("medical_document_question", "general_health_question"):
        if "query_medical_knowledge" in executed_tools:
            # Check if any other explicitly allowed tool hasn't been executed
            remaining = [t for t in request_scope.allowed_tools if t not in executed_tools]
            if not remaining:
                return PlannerDecision(
                    detected_intent=intent,
                    action="finish",
                    selection_reason=(
                        f"Completed medical knowledge retrieval via {agents_str}; "
                        "no further agents are needed."
                    ),
                )
        return None

    # 2. Medication Adherence Question
    if intent == "medication_adherence":
        med_obs = next(
            (o for o in reversed(observations) if o.get("tool_name") == "check_medication_adherence"),
            None,
        )
        if med_obs is None:
            return None
        med_inter = med_obs.get("intermediate_output") or {}
        if int(med_inter.get("active_medications_count", 0)) == 0:
            return PlannerDecision(
                detected_intent="insufficient_information",
                action="finish",
                selection_reason=(
                    "MedicationAgent reported 0 active medications for this user; "
                    "stopping without invoking additional agents."
                ),
                final_guidance=(
                    "No active medications are currently recorded in your profile. "
                    "Add a medication and schedule on the Medications page to track adherence."
                ),
            )
        if "monitor_health_metric" in request_scope.allowed_tools and "monitor_health_metric" not in executed_tools:
            return None
        if "query_medical_knowledge" in request_scope.allowed_tools and "query_medical_knowledge" not in executed_tools:
            return None
        return PlannerDecision(
            detected_intent="medication_adherence",
            action="finish",
            selection_reason=f"Completed medication adherence evaluation after executing {agents_str}.",
        )

    # 3. Alert Inspection
    if intent == "alert_inspection":
        if "inspect_active_alerts" in executed_tools:
            return PlannerDecision(
                detected_intent="alert_inspection",
                action="finish",
                selection_reason=f"Completed active alerts and reminders inspection via {agents_str}.",
            )
        return None

    # 4. Health Assessment (Request-Scoped to Target Metric)
    if intent == "health_assessment":
        mon_obs = next(
            (
                o
                for o in reversed(observations)
                if o.get("tool_name") == "monitor_health_metric"
                and (o.get("intermediate_output") or {}).get("metric_type") == target_metric
            ),
            None,
        )
        if mon_obs is None:
            return None

        mon_inter = mon_obs.get("intermediate_output") or {}
        readings_count = int(mon_inter.get("recent_readings_count", 0))
        mon_status = str(mon_inter.get("status", "normal"))
        is_urgent = bool(mon_inter.get("is_urgent", False))

        if readings_count == 0:
            return PlannerDecision(
                detected_intent="insufficient_information",
                action="finish",
                selection_reason=(
                    f"MonitoringAgent found 0 recorded measurements for {target_metric.replace('_', ' ')}; "
                    "terminating early rather than running risk or knowledge agents without data."
                ),
                final_guidance=(
                    f"Insufficient data: No measurements are currently recorded for {target_metric.replace('_', ' ')}. "
                    "Please log measurements on the Health Analytics page before running an assessment."
                ),
            )

        risk_obs = next(
            (
                o
                for o in reversed(observations)
                if o.get("tool_name") == "assess_health_risk"
                and (o.get("intermediate_output") or {}).get("metric_type") == target_metric
            ),
            None,
        )
        if readings_count >= 2 and risk_obs is None:
            return None

        risk_inter = (risk_obs or {}).get("intermediate_output") or {}
        risk_level = str(risk_inter.get("risk_level", "low"))

        if "check_medication_adherence" in request_scope.allowed_tools and "check_medication_adherence" not in executed_tools:
            return None

        wants_knowledge = (
            mon_status in ("deviation", "urgent_review")
            or is_urgent
            or risk_level in ("moderate", "high", "critical")
            or any(
                w in q_lower
                for w in ("guideline", "why", "explain", "reference", "knowledge", "what should", "target")
            )
        )
        if wants_knowledge and "query_medical_knowledge" not in executed_tools:
            return None

        if (
            allow_notification_delivery
            and minimal_context.get("pending_notification_events_count", 0) > 0
            and "deliver_pending_notifications" not in executed_tools
        ):
            return None

        return PlannerDecision(
            detected_intent="health_assessment",
            action="finish",
            selection_reason=(
                f"Completed health assessment for {target_metric.replace('_', ' ')} "
                f"(monitoring status='{mon_status}', rule-based risk='{risk_level}') "
                f"after executing {agents_str}."
            ),
        )

    # 5. Comprehensive Summary (Requires All Requested Domains to be Addressed)
    if intent == "comprehensive_summary":
        coverage = evaluate_domain_coverage(request_scope, observations, minimal_context)
        if coverage["unaddressed_domains"]:
            return None

        if (
            allow_notification_delivery
            and minimal_context.get("pending_notification_events_count", 0) > 0
            and "deliver_pending_notifications" not in executed_tools
        ):
            return None

        completed_str = ", ".join(coverage["completed_domains"]) or "none"
        unavail_str = (
            f"; unavailable domains (no records): {', '.join(coverage['unavailable_domains'])}"
            if coverage["unavailable_domains"]
            else ""
        )
        failed_str = (
            f"; failed domains: {', '.join(coverage['failed_domains'])}"
            if coverage["failed_domains"]
            else ""
        )
        return PlannerDecision(
            detected_intent="comprehensive_summary",
            action="finish",
            selection_reason=(
                f"Completed comprehensive health summary across requested domains "
                f"(addressed: [{completed_str}]{unavail_str}{failed_str}) "
                f"after executing {agents_str}."
            ),
        )

    return None


# ============================================================
# ADAPTIVE STEP-BY-STEP FALLBACK PLANNER
# ============================================================

def select_fallback_next_action(
    user_request: str,
    minimal_context: dict[str, Any],
    observations: list[dict[str, Any]],
    executed_signatures: set[str],
    preferred_metric: Optional[str] = None,
    allow_notification_delivery: bool = False,
) -> PlannerDecision:
    """
    Adaptive step-by-step fallback decision maker used when Ollama is offline
    or after bounded LLM retries fail.

    Crucially, this function inspects `observations` from already-completed steps
    at each iteration rather than pre-computing a static list of tools.
    """
    intent = classify_request_intent(user_request)
    target_metric = infer_target_metric(user_request, minimal_context, preferred_metric)
    q_lower = (user_request or "").lower()
    executed_tools = [obs.get("tool_name") for obs in observations]

    def _can_call(tool_name: str, args: dict[str, Any]) -> bool:
        try:
            clean_name, val_args = validate_tool_call(tool_name, args)
            sig = canonical_tool_signature(clean_name, val_args)
            return sig not in executed_signatures
        except ToolValidationError:
            return False

    # ----------------------------------------------------------
    # Scenario 1: Medical Document / Clinical Knowledge Question
    # ----------------------------------------------------------
    if intent in ("medical_document_question", "general_health_question"):
        asks_personal_doc = any(
            phrase in q_lower
            for phrase in ("my report", "my lab", "uploaded", "my pdf", "my document", "in my medical report")
        )
        if asks_personal_doc and minimal_context.get("uploaded_documents_count", 0) == 0:
            return PlannerDecision(
                detected_intent="insufficient_information",
                action="finish",
                selection_reason=(
                    "User asked about an uploaded personal medical document, "
                    "but 0 uploaded documents exist for this profile."
                ),
                final_guidance=(
                    "No uploaded medical PDF documents were found in your profile. "
                    "Please upload and index a PDF report on the Medical Documents page first."
                ),
            )

        if "query_medical_knowledge" not in executed_tools:
            args = {
                "question": user_request.strip()[:500],
                "include_user_documents": True,
                "include_global_knowledge": True,
                "n_results": 3,
            }
            if _can_call("query_medical_knowledge", args):
                return PlannerDecision(
                    detected_intent=intent,
                    action="call_tool",
                    tool_name="query_medical_knowledge",
                    tool_args=args,
                    selection_reason=(
                        "Selected MedicalKnowledgeAgent to retrieve grounded evidence and source "
                        "citations from indexed documents without invoking unrelated monitoring or medication agents."
                    ),
                )

        return PlannerDecision(
            detected_intent=intent,
            action="finish",
            selection_reason="Medical knowledge retrieval completed; no further agents are needed.",
        )

    # ----------------------------------------------------------
    # Scenario 2: Medication Adherence Question
    # ----------------------------------------------------------
    if intent == "medication_adherence":
        if "check_medication_adherence" not in executed_tools:
            args = {"refresh_reminders": True}
            if _can_call("check_medication_adherence", args):
                return PlannerDecision(
                    detected_intent="medication_adherence",
                    action="call_tool",
                    tool_name="check_medication_adherence",
                    tool_args=args,
                    selection_reason=(
                        "Selected MedicationAgent to inspect active prescriptions, scheduled dose occurrences, "
                        "adherence percentages, and pending reminders."
                    ),
                )

        # Inspect intermediate result of check_medication_adherence
        med_obs = next(
            (o for o in reversed(observations) if o.get("tool_name") == "check_medication_adherence"),
            None,
        )
        med_inter = (med_obs or {}).get("intermediate_output") or {}
        if med_inter.get("active_medications_count", 0) == 0:
            return PlannerDecision(
                detected_intent="insufficient_information",
                action="finish",
                selection_reason=(
                    "MedicationAgent reported 0 active medications for this user; "
                    "stopping without invoking additional agents."
                ),
                final_guidance=(
                    "No active medications are currently recorded in your profile. "
                    "Add a medication and schedule on the Medications page to track adherence."
                ),
            )

        # Only invoke MonitoringAgent if the user's question also asks about physiological measurements
        mentions_metric = any(
            any(kw in q_lower for kw in kws) for _, kws in METRIC_KEYWORDS
        )
        if mentions_metric and "monitor_health_metric" not in executed_tools:
            m_args = {"metric_type": target_metric}
            if _can_call("monitor_health_metric", m_args):
                return PlannerDecision(
                    detected_intent="medication_adherence",
                    action="call_tool",
                    tool_name="monitor_health_metric",
                    tool_args=m_args,
                    selection_reason=(
                        f"User request also referenced {target_metric.replace('_', ' ')}; "
                        "invoking MonitoringAgent to correlate recent readings with medication adherence."
                    ),
                )

        return PlannerDecision(
            detected_intent="medication_adherence",
            action="finish",
            selection_reason="Medication adherence evaluation is complete; unrelated agents were skipped.",
        )

    # ----------------------------------------------------------
    # Scenario 3: Alert Inspection
    # ----------------------------------------------------------
    if intent == "alert_inspection":
        if "inspect_active_alerts" not in executed_tools:
            args = {"limit": 10}
            if _can_call("inspect_active_alerts", args):
                return PlannerDecision(
                    detected_intent="alert_inspection",
                    action="call_tool",
                    tool_name="inspect_active_alerts",
                    tool_args=args,
                    selection_reason=(
                        "Selected NotificationAgent in read-only inspection mode to review "
                        "unacknowledged monitoring events and pending medication reminders."
                    ),
                )
        return PlannerDecision(
            detected_intent="alert_inspection",
            action="finish",
            selection_reason="Active alerts and reminders have been inspected.",
        )

    # ----------------------------------------------------------
    # Scenario 4: Health Assessment (Adaptive to Intermediate Output)
    # ----------------------------------------------------------
    if intent == "health_assessment":
        # Step 1: Always inspect the target metric with MonitoringAgent first
        if "monitor_health_metric" not in executed_tools:
            m_args = {"metric_type": target_metric}
            if _can_call("monitor_health_metric", m_args):
                return PlannerDecision(
                    detected_intent="health_assessment",
                    action="call_tool",
                    tool_name="monitor_health_metric",
                    tool_args=m_args,
                    selection_reason=(
                        f"Selected MonitoringAgent first to inspect recent {target_metric.replace('_', ' ')} "
                        "measurements and evaluate statistical status."
                    ),
                )

        # Inspect actual observation from MonitoringAgent
        mon_obs = next(
            (o for o in reversed(observations) if o.get("tool_name") == "monitor_health_metric"),
            None,
        )
        mon_inter = (mon_obs or {}).get("intermediate_output") or {}
        readings_count = int(mon_inter.get("recent_readings_count", 0))
        mon_status = str(mon_inter.get("status", "normal"))
        is_urgent = bool(mon_inter.get("is_urgent", False))

        # Adaptive Branch A: 0 readings -> terminate immediately (Insufficient Data)
        if readings_count == 0:
            return PlannerDecision(
                detected_intent="insufficient_information",
                action="finish",
                selection_reason=(
                    f"MonitoringAgent found 0 recorded measurements for {target_metric.replace('_', ' ')}; "
                    "terminating early rather than running risk or knowledge agents without data."
                ),
                final_guidance=(
                    f"Insufficient data: No measurements are currently recorded for {target_metric.replace('_', ' ')}. "
                    "Please log measurements on the Health Analytics page before running an assessment."
                ),
            )

        # Adaptive Branch B: >= 2 readings -> run RiskAssessmentAgent to evaluate longitudinal trend
        if readings_count >= 2 and "assess_health_risk" not in executed_tools:
            r_args = {"metric_type": target_metric, "include_experimental_ml": False}
            if _can_call("assess_health_risk", r_args):
                return PlannerDecision(
                    detected_intent="health_assessment",
                    action="call_tool",
                    tool_name="assess_health_risk",
                    tool_args=r_args,
                    selection_reason=(
                        f"MonitoringAgent found {readings_count} readings (status='{mon_status}'); "
                        "invoking RiskAssessmentAgent to evaluate longitudinal trends and risk level."
                    ),
                )

        # Inspect actual observation from RiskAssessmentAgent (if run)
        risk_obs = next(
            (o for o in reversed(observations) if o.get("tool_name") == "assess_health_risk"),
            None,
        )
        risk_inter = (risk_obs or {}).get("intermediate_output") or {}
        risk_level = str(risk_inter.get("risk_level", "low"))

        # Adaptive Branch C: If user also asked about medication OR if glucose/BP risk is elevated and user has active meds
        asks_med = any(w in q_lower for w in ("medication", "adherence", "dose", "metformin", "pill"))
        if asks_med and "check_medication_adherence" not in executed_tools:
            if _can_call("check_medication_adherence", {"refresh_reminders": True}):
                return PlannerDecision(
                    detected_intent="health_assessment",
                    action="call_tool",
                    tool_name="check_medication_adherence",
                    tool_args={"refresh_reminders": True},
                    selection_reason=(
                        "Request includes medication context alongside metric assessment; "
                        "invoking MedicationAgent to check adherence."
                    ),
                )

        # Adaptive Branch D: Decide whether MedicalKnowledgeAgent is warranted based on actual intermediate results
        wants_knowledge = (
            mon_status in ("deviation", "urgent_review")
            or is_urgent
            or risk_level in ("moderate", "high", "critical")
            or any(w in q_lower for w in ("guideline", "why", "explain", "reference", "knowledge", "what should", "target"))
        )
        if wants_knowledge and "query_medical_knowledge" not in executed_tools:
            clean_metric = target_metric.replace("_", " ")
            if is_urgent:
                k_query = f"Emergency clinical guidance and safety precautions for critical {clean_metric} values."
            elif mon_status == "deviation" or risk_level in ("moderate", "high", "critical"):
                k_query = f"Clinical guidelines for monitoring and managing elevated or deviating {clean_metric} trends."
            else:
                k_query = f"Standard clinical reference ranges and educational recommendations for {clean_metric}."
            k_args = {
                "question": k_query,
                "include_user_documents": True,
                "include_global_knowledge": True,
                "n_results": 2,
            }
            if _can_call("query_medical_knowledge", k_args):
                return PlannerDecision(
                    detected_intent="health_assessment",
                    action="call_tool",
                    tool_name="query_medical_knowledge",
                    tool_args=k_args,
                    selection_reason=(
                        f"Intermediate findings showed monitoring status='{mon_status}' and risk='{risk_level}'; "
                        "invoking MedicalKnowledgeAgent to retrieve grounded clinical references."
                    ),
                )

        # Adaptive Branch E: Deliver notifications only when authorized and pending events exist
        if (
            allow_notification_delivery
            and minimal_context.get("pending_notification_events_count", 0) > 0
            and "deliver_pending_notifications" not in executed_tools
        ):
            if _can_call("deliver_pending_notifications", {}):
                return PlannerDecision(
                    detected_intent="health_assessment",
                    action="call_tool",
                    tool_name="deliver_pending_notifications",
                    tool_args={},
                    selection_reason=(
                        "Authorized notification delivery requested and pending monitoring events exist; "
                        "invoking NotificationAgent."
                    ),
                )

        return PlannerDecision(
            detected_intent="health_assessment",
            action="finish",
            selection_reason=(
                f"Health assessment for {target_metric.replace('_', ' ')} completed based on "
                f"observed monitoring status ('{mon_status}') and risk level ('{risk_level}')."
            ),
        )

    # ----------------------------------------------------------
    # Scenario 5: Comprehensive Personalized Health Summary
    # ----------------------------------------------------------
    total_meas = minimal_context.get("total_measurements", 0)
    active_meds = minimal_context.get("active_medications_count", 0)
    uploaded_docs = minimal_context.get("uploaded_documents_count", 0)

    if total_meas == 0 and active_meds == 0 and uploaded_docs == 0:
        return PlannerDecision(
            detected_intent="insufficient_information",
            action="finish",
            selection_reason=(
                "Profile currently has 0 measurements, 0 active medications, and 0 uploaded documents; "
                "cannot generate a personalized summary without health records."
            ),
            final_guidance=(
                "Your profile does not yet have recorded health measurements, active medications, "
                "or uploaded documents. Add measurements in Health Analytics or medications in "
                "Medication Management to generate a personalized summary."
            ),
        )

    if total_meas > 0 and "monitor_health_metric" not in executed_tools:
        m_args = {"metric_type": target_metric}
        if _can_call("monitor_health_metric", m_args):
            return PlannerDecision(
                detected_intent="comprehensive_summary",
                action="call_tool",
                tool_name="monitor_health_metric",
                tool_args=m_args,
                selection_reason=(
                    f"Selected MonitoringAgent to evaluate primary metric ({target_metric.replace('_', ' ')}) "
                    "for the comprehensive health summary."
                ),
            )

    mon_obs = next(
        (o for o in reversed(observations) if o.get("tool_name") == "monitor_health_metric"),
        None,
    )
    mon_inter = (mon_obs or {}).get("intermediate_output") or {}
    if int(mon_inter.get("recent_readings_count", 0)) >= 2 and "assess_health_risk" not in executed_tools:
        r_args = {"metric_type": target_metric, "include_experimental_ml": False}
        if _can_call("assess_health_risk", r_args):
            return PlannerDecision(
                detected_intent="comprehensive_summary",
                action="call_tool",
                tool_name="assess_health_risk",
                tool_args=r_args,
                selection_reason=(
                    "Sufficient metric readings observed; invoking RiskAssessmentAgent "
                    "to include longitudinal trend and risk analysis in the summary."
                ),
            )

    asks_med_in_summary = any(
        w in q_lower
        for w in ("medication", "medications", "medicine", "adherence", "dose", "doses", "pill", "prescription")
    )
    if (active_meds > 0 or asks_med_in_summary) and "check_medication_adherence" not in executed_tools:
        if _can_call("check_medication_adherence", {"refresh_reminders": True}):
            return PlannerDecision(
                detected_intent="comprehensive_summary",
                action="call_tool",
                tool_name="check_medication_adherence",
                tool_args={"refresh_reminders": True},
                selection_reason=(
                    "Invoking MedicationAgent to evaluate active medications, scheduled dose adherence, "
                    "taken/missed/overdue counts, and reminders for the comprehensive summary."
                ),
            )

    if "query_medical_knowledge" not in executed_tools:
        clean_metric = target_metric.replace("_", " ")
        k_args = {
            "question": f"General clinical reference guidelines and health maintenance targets for {clean_metric}.",
            "include_user_documents": True,
            "include_global_knowledge": True,
            "n_results": 2,
        }
        if _can_call("query_medical_knowledge", k_args):
            return PlannerDecision(
                detected_intent="comprehensive_summary",
                action="call_tool",
                tool_name="query_medical_knowledge",
                tool_args=k_args,
                selection_reason=(
                    "Selected MedicalKnowledgeAgent to attach grounded clinical references "
                    "and user document context to the comprehensive summary."
                ),
            )

    has_alerts = (
        minimal_context.get("unread_monitoring_events_count", 0) > 0
        or minimal_context.get("pending_medication_reminders_count", 0) > 0
    )
    if (
        has_alerts
        and "inspect_active_alerts" not in executed_tools
        and "deliver_pending_notifications" not in executed_tools
    ):
        if allow_notification_delivery and minimal_context.get("pending_notification_events_count", 0) > 0:
            if _can_call("deliver_pending_notifications", {}):
                return PlannerDecision(
                    detected_intent="comprehensive_summary",
                    action="call_tool",
                    tool_name="deliver_pending_notifications",
                    tool_args={},
                    selection_reason="Delivering eligible pending monitoring notifications for the summary.",
                )
        elif _can_call("inspect_active_alerts", {"limit": 10}):
            return PlannerDecision(
                detected_intent="comprehensive_summary",
                action="call_tool",
                tool_name="inspect_active_alerts",
                tool_args={"limit": 10},
                selection_reason="Inspecting active monitoring events and medication reminders for the summary.",
            )

    return PlannerDecision(
        detected_intent="comprehensive_summary",
        action="finish",
        selection_reason="All relevant available health domains have been gathered for the comprehensive summary.",
    )


# ============================================================
# PUBLIC ENTRYPOINT: SELECT NEXT ACTION IN LOOP
# ============================================================

def select_next_action(
    user_request: str,
    minimal_context: dict[str, Any],
    observations: list[dict[str, Any]],
    executed_signatures: set[str],
    preferred_metric: Optional[str] = None,
    allow_notification_delivery: bool = False,
    request_scope: Optional[RequestToolScope] = None,
) -> ValidatedPlannerStep:
    """
    Execute one planning decision in the iterative loop:
    1. Build or apply the request-scoped tool & metric constraints (`RequestToolScope`).
    2. Check `evaluate_execution_sufficiency` to stop cleanly once all in-scope evidence
       required for the request has been gathered.
    3. If Ollama is reachable, query `llama3.1` with bounded retries (`MAX_PLANNER_RETRIES`).
    4. Validate the proposed tool call against the allowlist, Pydantic argument schema,
       request-scoped metric/tool constraints, identity-override rules, and duplicate-call signature set.
    5. Preserve the original request intent throughout execution (unless transitioning to
       `insufficient_information`).
    6. If Ollama is offline or fails validation after bounded retries, fall back to
       `select_fallback_next_action` and record any rejection notes for the execution trace.
    """
    rejection_notes: list[str] = []
    planner_llm_ms = 0

    if request_scope is None:
        initial_intent = classify_request_intent(user_request)
        request_scope = build_request_tool_scope(
            user_request=user_request,
            initial_intent=initial_intent,
            minimal_context=minimal_context,
            preferred_metric=preferred_metric,
            allow_notification_delivery=allow_notification_delivery,
        )

    locked_intent: PlannerIntent = request_scope.initial_intent  # type: ignore[assignment]
    provider = get_active_llm_provider()

    try:
        llm_online = check_groq_available() if provider == "groq" else check_ollama_available()
    except Exception:
        llm_online = False

    # Check if already-executed in-scope tools have sufficiently answered the request
    sufficiency_decision = evaluate_execution_sufficiency(
        user_request=user_request,
        minimal_context=minimal_context,
        observations=observations,
        request_scope=request_scope,
        allow_notification_delivery=allow_notification_delivery,
    )
    if sufficiency_decision is not None:
        return ValidatedPlannerStep(
            decision=sufficiency_decision,
            planner_mode="deterministic_fallback",
            rejection_notes=rejection_notes,
            planner_llm_ms=0,
        )

    if llm_online:
        retry_feedback: Optional[str] = None
        for attempt in range(1, MAX_PLANNER_RETRIES + 1):
            t_llm = time.time()
            try:
                planner_call = _call_groq_planner_once if provider == "groq" else _call_ollama_planner_once
                decision = planner_call(
                    user_request=user_request,
                    minimal_context=minimal_context,
                    observations=observations,
                    executed_signatures=executed_signatures,
                    preferred_metric=preferred_metric or request_scope.primary_metric,
                    allow_notification_delivery=allow_notification_delivery,
                    retry_feedback=retry_feedback,
                    request_scope=request_scope,
                )
                planner_llm_ms += int((time.time() - t_llm) * 1000)

                # Preserve initial request intent unless transitioning to insufficient_information
                if decision.detected_intent != "insufficient_information":
                    decision.detected_intent = locked_intent

                if decision.action == "finish":
                    coverage = evaluate_domain_coverage(request_scope, observations, minimal_context)
                    if coverage["unaddressed_domains"]:
                        raise ToolValidationError(
                            f"Premature finish rejected: explicitly requested domain(s) "
                            f"{coverage['unaddressed_domains']} remain unaddressed. "
                            f"Select an appropriate tool ({coverage['required_next_tools']}) to address "
                            "the remaining requested domain(s) before finishing."
                        )
                    return ValidatedPlannerStep(
                        decision=decision,
                        planner_mode="llm_assisted",
                        rejection_notes=rejection_notes,
                        planner_llm_ms=planner_llm_ms,
                    )

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
                    raise ToolValidationError(
                        f"Duplicate tool call blocked: '{sig}' was already executed in this workflow."
                    )

                decision.tool_name = clean_tool
                decision.tool_args = validated_args
                return ValidatedPlannerStep(
                    decision=decision,
                    planner_mode="llm_assisted",
                    rejection_notes=rejection_notes,
                    planner_llm_ms=planner_llm_ms,
                )

            except (ToolValidationError, ValidationError, ValueError, httpx.HTTPError, Exception) as exc:
                planner_llm_ms += int((time.time() - t_llm) * 1000)
                safe_err = str(exc)
                if provider == "groq" and isinstance(exc, httpx.HTTPStatusError):
                    safe_err = f"Groq HTTP {exc.response.status_code}"
                note = f"LLM planner ({provider}) attempt {attempt}/{MAX_PLANNER_RETRIES} rejected: {safe_err}"
                logger.warning(note)
                rejection_notes.append(note)
                retry_feedback = safe_err
    else:
        provider_label = "Groq cloud LLM" if provider == "groq" else "Local Ollama"
        rejection_notes.append(
            f"{provider_label} service unavailable; using adaptive deterministic fallback planner."
        )

    fallback_decision = select_fallback_next_action(
        user_request=user_request,
        minimal_context=minimal_context,
        observations=observations,
        executed_signatures=executed_signatures,
        preferred_metric=preferred_metric or request_scope.primary_metric,
        allow_notification_delivery=allow_notification_delivery,
    )
    if fallback_decision.detected_intent != "insufficient_information":
        fallback_decision.detected_intent = locked_intent

    return ValidatedPlannerStep(
        decision=fallback_decision,
        planner_mode="deterministic_fallback",
        rejection_notes=rejection_notes,
        planner_llm_ms=planner_llm_ms,
    )

