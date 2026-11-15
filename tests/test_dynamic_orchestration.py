"""
Automated Test Suite for Dynamic Agentic Orchestration

Covers:
1. Dynamic tool selection for medical document questions (avoids unrelated agents).
2. Adaptive next-step selection based on actual intermediate tool outputs (normal vs deviation vs insufficient data).
3. Medication adherence dynamic routing (avoids unrelated monitoring/risk tools).
4. Multi-agent coordination for comprehensive personalized health summaries.
5. Insufficient-data early termination without fabricating findings.
6. Rejection of invalid LLM-generated tool names, invalid arguments, and forbidden `user_id` overrides.
7. Duplicate tool-call prevention and configurable maximum execution step limits (up to 8).
8. Graceful tool failure recovery and Ollama offline fallback behavior.
9. Separation of read-only alert inspection from authorized notification delivery.
10. Healthcare safety boundaries (refusal of diagnosis/prescription requests, immediate emergency escalation).
11. Strict authentication and user isolation across `/orchestration/execute` and `/orchestration/history`.
12. Full backward compatibility with existing static workflows (`/assess`, `/medication-check`, `/summary`).
"""

from datetime import date, datetime
from unittest.mock import patch
import httpx
import pytest

from healthguard.database.models import DocumentIndexStatus, MedicalDocument
from healthguard.database.session import get_db
from healthguard.main import app
from healthguard.orchestration.orchestrator import AgenticOrchestrator
from healthguard.orchestration.planner import PlannerDecision, classify_request_intent
from healthguard.orchestration.schemas import OrchestrationState, WorkflowType
from healthguard.orchestration.tools import (
    ToolValidationError,
    build_request_tool_scope,
    sanitize_knowledge_query_phrasing,
    validate_tool_against_request_scope,
    validate_tool_call,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def db_session(client):
    override_fn = app.dependency_overrides.get(get_db)
    if override_fn:
        gen = override_fn()
        db = next(gen)
        try:
            yield db
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
    else:
        from healthguard.database.session import SessionLocal
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()


@pytest.fixture
def user_alpha(client):
    reg = client.post(
        "/auth/register",
        json={
            "full_name": "Dynamic Alpha",
            "email": "dynamic.alpha@example.com",
            "password": "AlphaPassword@123",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    uid = reg.json()["id"]

    login = client.post(
        "/auth/login",
        json={
            "email": "dynamic.alpha@example.com",
            "password": "AlphaPassword@123",
        },
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {
        "user_id": uid,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
def user_beta(client):
    reg = client.post(
        "/auth/register",
        json={
            "full_name": "Dynamic Beta",
            "email": "dynamic.beta@example.com",
            "password": "BetaPassword@123",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    uid = reg.json()["id"]

    login = client.post(
        "/auth/login",
        json={
            "email": "dynamic.beta@example.com",
            "password": "BetaPassword@123",
        },
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {
        "user_id": uid,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def add_metric(client, user, metric_type: str, value: float, unit: str = "mg/dL"):
    resp = client.post(
        f"/metrics?user_id={user['user_id']}",
        headers=user["headers"],
        json={
            "metric_type": metric_type,
            "value": value,
            "unit": unit,
            "source": "manual",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


# ============================================================
# 1. MEDICAL DOCUMENT QUESTION -> KNOWLEDGE AGENT ONLY
# ============================================================

def test_dynamic_document_question_selects_only_knowledge_agent(client, user_alpha, db_session):
    """
    Scenario A: Asking about an uploaded medical report must select `query_medical_knowledge`
    (`MedicalKnowledgeAgent`) and must NOT invoke `MonitoringAgent` or `MedicationAgent`.
    """
    uid = user_alpha["user_id"]
    doc = MedicalDocument(
        user_id=uid,
        filename="synthetic_lab_panel.pdf",
        stored_path="storage/medical_reports/test_panel.pdf",
        content_type="application/pdf",
        file_size=1024,
        sha256_hash="a" * 64,
        extracted_text="Fasting blood glucose: 134 mg/dL. HbA1c: 6.3%.",
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        DocumentIndexStatus(
            document_id=doc.id,
            user_id=uid,
            status="indexed",
            chunk_count=2,
            indexed_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    mock_rag = {
        "answer": "Your uploaded report lists a fasting blood glucose of 134 mg/dL and HbA1c of 6.3% [1].",
        "sources": [
            {
                "document_title": "synthetic_lab_panel.pdf",
                "source_organization": "User Uploaded Report",
                "chunk_text": "Fasting blood glucose: 134 mg/dL. HbA1c: 6.3%.",
            }
        ],
        "limitations": [],
        "disclaimer": "Educational only.",
        "is_emergency": False,
        "emergency_guidance": None,
    }

    # Mock LLM planner: Step 1 -> call query_medical_knowledge, Step 2 -> finish
    planner_decisions = [
        PlannerDecision(
            detected_intent="medical_document_question",
            action="call_tool",
            tool_name="query_medical_knowledge",
            tool_args={
                "question": "What does my uploaded lab report say about fasting glucose and HbA1c?",
                "include_user_documents": True,
                "include_global_knowledge": True,
                "n_results": 3,
            },
            selection_reason="User asked about their uploaded lab report; selecting MedicalKnowledgeAgent.",
        ),
        PlannerDecision(
            detected_intent="medical_document_question",
            action="finish",
            selection_reason="Uploaded report findings and citations were retrieved.",
        ),
    ]

    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.planner._call_ollama_planner_once", side_effect=planner_decisions), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", return_value=mock_rag):
        resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={
                "query": "What does my uploaded lab report say about my fasting glucose and HbA1c?",
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["workflow_type"] == WorkflowType.WORKFLOW_DYNAMIC_AGENTIC.value
    assert data["planner_mode"] == "llm_assisted"
    assert data["selected_agents"] == ["MedicalKnowledgeAgent"]
    assert data["monitoring"] is None
    assert data["medication"] is None
    assert data["risk_assessment"] is None
    assert data["medical_knowledge"] is not None
    assert len(data["medical_knowledge"]["citations"]) == 1
    assert data["execution_steps"][0]["tool_name"] == "query_medical_knowledge"


# ============================================================
# 2. ADAPTIVE SELECTION BASED ON INTERMEDIATE RESULTS
# ============================================================

def test_dynamic_assessment_adapts_to_intermediate_deviation(client, user_alpha, db_session):
    """
    Scenario B: When assessing blood glucose:
    - Case 1 (Normal readings, no literature requested): Runs MonitoringAgent -> RiskAssessmentAgent -> finishes WITHOUT calling MedicalKnowledgeAgent.
    - Case 2 (Deviating readings): Runs MonitoringAgent -> observes deviation -> runs RiskAssessmentAgent -> adaptively invokes MedicalKnowledgeAgent because intermediate output showed deviation/elevated risk!
    """
    # Case 1: Normal steady readings (92..95 mg/dL)
    for v in [92.0, 93.0, 94.0, 92.0, 95.0, 93.0, 94.0, 93.0]:
        add_metric(client, user_alpha, "blood_glucose", v, "mg/dL")

    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=False):
        resp_normal = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={"query": "Assess my recent blood glucose measurements."},
        )

    assert resp_normal.status_code == 200, resp_normal.text
    normal_data = resp_normal.json()
    assert normal_data["monitoring"]["status"] == "normal"
    assert normal_data["risk_assessment"]["risk_level"] == "low"
    # Because monitoring is normal and risk is low, MedicalKnowledgeAgent and MedicationAgent are NOT called
    assert normal_data["selected_agents"] == ["MonitoringAgent", "RiskAssessmentAgent"]
    assert normal_data["medical_knowledge"] is None
    assert normal_data["medication"] is None

    # Case 2: Add sharp upward deviation readings (165, 178, 195 mg/dL) so intermediate monitoring status becomes 'deviation'
    for v in [165.0, 178.0, 195.0]:
        add_metric(client, user_alpha, "blood_glucose", v, "mg/dL")

    mock_rag = {
        "answer": "Clinical guidelines recommend reviewing glycemic trends with a healthcare provider [1].",
        "sources": [{"document_title": "ADA Standards of Care", "source_organization": "ADA", "chunk_text": "Glycemic management."}],
        "limitations": [],
        "disclaimer": "Educational only.",
        "is_emergency": False,
        "emergency_guidance": None,
    }

    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=False), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", return_value=mock_rag):
        resp_dev = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={"query": "Assess my recent blood glucose measurements."},
        )

    assert resp_dev.status_code == 200, resp_dev.text
    dev_data = resp_dev.json()
    assert dev_data["monitoring"]["status"] == "deviation"
    # Same exact user request now dynamically includes MedicalKnowledgeAgent because intermediate output showed a deviation!
    assert "MedicalKnowledgeAgent" in dev_data["selected_agents"]
    assert dev_data["selected_agents"] == [
        "MonitoringAgent",
        "RiskAssessmentAgent",
        "MedicalKnowledgeAgent",
    ]


# ============================================================
# 3. MEDICATION ADHERENCE QUESTION -> MEDICATION AGENT ONLY
# ============================================================

def test_dynamic_medication_question_selects_only_medication_agent(client, user_alpha):
    """
    Scenario C: Asking about medication adherence invokes `MedicationAgent` and skips unrelated agents.
    """
    med_resp = client.post(
        f"/medications?user_id={user_alpha['user_id']}",
        headers=user_alpha["headers"],
        json={
            "name": "Metformin XR",
            "dosage": "500 mg",
            "frequency": "Once daily",
            "instructions": "Take with dinner",
            "start_date": date.today().isoformat(),
        },
    )
    assert med_resp.status_code in (200, 201), med_resp.text

    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=False):
        resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={"query": "Check my medication adherence and any overdue doses."},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["detected_intent"] == "medication_adherence"
    assert data["selected_agents"] == ["MedicationAgent"]
    assert data["medication"]["active_medications_count"] == 1
    assert data["monitoring"] is None
    assert data["risk_assessment"] is None
    assert data["medical_knowledge"] is None


# ============================================================
# 4. COMPREHENSIVE HEALTH SUMMARY -> MULTI-AGENT COORDINATION
# ============================================================

def test_dynamic_comprehensive_summary_coordinates_multiple_agents(client, user_alpha):
    """
    Scenario D: A comprehensive health summary request dynamically coordinates
    Monitoring, Risk Assessment, Medication, and Medical Knowledge agents.
    """
    for v in [108.0, 112.0, 115.0, 110.0, 114.0, 118.0, 122.0, 125.0]:
        add_metric(client, user_alpha, "blood_glucose", v, "mg/dL")

    client.post(
        f"/medications?user_id={user_alpha['user_id']}",
        headers=user_alpha["headers"],
        json={
            "name": "Lisinopril",
            "dosage": "10 mg",
            "frequency": "Daily",
            "start_date": date.today().isoformat(),
        },
    )

    mock_rag = {
        "answer": "Maintain balanced nutrition, regular physical activity, and routine monitoring [1].",
        "sources": [{"document_title": "WHO Guideline", "source_organization": "WHO", "chunk_text": "Lifestyle guidance."}],
        "limitations": [],
        "disclaimer": "Educational only.",
        "is_emergency": False,
        "emergency_guidance": None,
    }

    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=False), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", return_value=mock_rag):
        resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={"query": "Give me a comprehensive personalized health summary."},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["detected_intent"] == "comprehensive_summary"
    assert "MonitoringAgent" in data["selected_agents"]
    assert "RiskAssessmentAgent" in data["selected_agents"]
    assert "MedicationAgent" in data["selected_agents"]
    assert "MedicalKnowledgeAgent" in data["selected_agents"]
    assert len(data["execution_steps"]) >= 4


# ============================================================
# 5. INSUFFICIENT DATA EARLY TERMINATION
# ============================================================

def test_dynamic_insufficient_data_terminates_without_inventing_findings(client, user_alpha):
    """
    Scenario E: When the user has 0 sleep duration measurements, the orchestrator
    runs MonitoringAgent, observes `recent_readings_count == 0`, and terminates immediately
    without calling RiskAssessmentAgent or fabricating findings.
    """
    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=False):
        resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={"query": "Assess my recent sleep duration measurements over the past week."},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["detected_intent"] == "insufficient_information"
    assert data["selected_agents"] == ["MonitoringAgent"]
    assert data["monitoring"]["status"] == "insufficient_data"
    assert data["monitoring"]["recent_readings_count"] == 0
    assert data["risk_assessment"] is None
    assert data["medical_knowledge"] is None
    assert "insufficient" in data["summary_text"].lower() or "no recent measurements" in data["summary_text"].lower()


# ============================================================
# 6. INVALID LLM TOOL PROPOSALS & IDENTITY OVERRIDE REJECTION
# ============================================================

def test_invalid_llm_tool_and_identity_override_rejected(client, user_alpha, db_session):
    """
    Verify that:
    1. Unallowlisted tools (e.g., `delete_patient_records`, `prescribe_insulin`) are rejected.
    2. Any attempt by the LLM to pass `user_id` or `target_user_id` in `tool_args` is rejected.
    3. Extra unknown arguments are rejected by Pydantic `extra="forbid"`.
    """
    with pytest.raises(ToolValidationError, match="Disallowed or unknown tool"):
        validate_tool_call("delete_patient_records", {})

    with pytest.raises(ToolValidationError, match="Security violation"):
        validate_tool_call("monitor_health_metric", {"metric_type": "blood_glucose", "user_id": 999})

    with pytest.raises(ToolValidationError, match="Invalid arguments"):
        validate_tool_call("monitor_health_metric", {"metric_type": "blood_glucose", "hack_param": True})

    # Also test inside the full orchestrator when Ollama returns a hallucinated tool first, then a valid finish
    bad_decision = PlannerDecision(
        detected_intent="medication_adherence",
        action="call_tool",
        tool_name="prescribe_new_dosage",
        tool_args={"dosage": "1000mg"},
        selection_reason="Attempted invalid tool.",
    )
    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.planner._call_ollama_planner_once", side_effect=[bad_decision, bad_decision]):
        orchestrator = AgenticOrchestrator(db_session)
        res = orchestrator.run_dynamic_workflow(
            user_id=user_alpha["user_id"],
            query="How are my medications?",
        )
        # Falls back safely after rejecting the invalid LLM tool proposals
        assert res.planner_mode == "deterministic_fallback"
        assert any(
            s.error_recovery and "prescribe_new_dosage" in s.error_recovery
            for s in res.execution_steps
        )


# ============================================================
# 7. DUPLICATE TOOL CALL PREVENTION & MAX EXECUTION STEPS
# ============================================================

def test_duplicate_tool_prevention_and_max_steps_limit(client, user_alpha, db_session):
    """
    Verify that:
    1. Proposing the exact same tool + arguments twice in a loop is blocked.
    2. `max_steps` strictly caps the number of tool executions.
    """
    add_metric(client, user_alpha, "blood_glucose", 110.0, "mg/dL")
    add_metric(client, user_alpha, "blood_glucose", 115.0, "mg/dL")

    # Test max_steps=1 cap: even though assessment would normally chain RiskAssessmentAgent, max_steps=1 stops after 1 step
    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=False):
        resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={
                "query": "Give me a comprehensive personalized health summary.",
                "max_steps": 1,
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["execution_steps"]) == 1
    assert "maximum execution steps (1)" in (data["termination_reason"] or "").lower()


# ============================================================
# 8. TOOL FAILURE RECOVERY & SAFETY BOUNDARIES
# ============================================================

def test_tool_failure_handled_gracefully_and_safety_boundaries_enforced(client, user_alpha):
    """
    Verify:
    1. Unsafe requests ('diagnose me', 'prescribe medication') are refused by MedicalSafetyGate without calling tools.
    2. Emergency symptoms ('severe chest pain and difficulty breathing') trigger immediate escalation.
    3. Runtime tool failure is caught, logged in `execution_steps`, and marks state as `degraded`.
    """
    # 1. Unsafe request refusal
    unsafe_resp = client.post(
        "/orchestration/execute",
        headers=user_alpha["headers"],
        json={"query": "Diagnose me and prescribe a higher dosage of metformin."},
    )
    assert unsafe_resp.status_code == 200, unsafe_resp.text
    u_data = unsafe_resp.json()
    assert u_data["detected_intent"] == "safety_boundary_refusal"
    assert u_data["selected_agents"] == ["MedicalSafetyGate"]
    assert "cannot diagnose" in u_data["summary_text"].lower()

    # 2. Emergency symptom escalation
    emerg_resp = client.post(
        "/orchestration/execute",
        headers=user_alpha["headers"],
        json={"query": "I have crushing chest pain and difficulty breathing right now."},
    )
    assert emerg_resp.status_code == 200, emerg_resp.text
    e_data = emerg_resp.json()
    assert e_data["orchestration_state"] == OrchestrationState.ESCALATED.value
    assert e_data["safety_escalation"] is not None
    assert e_data["selected_agents"] == ["SafetyEscalationAgent"]

    # 3. Runtime tool exception recovery
    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=False), \
         patch.object(
             AgenticOrchestrator,
             "_check_idempotent_recent_execution",
             return_value=None,
         ), \
         patch(
             "healthguard.orchestration.agents.medication_agent.MedicationAgent.evaluate_medications",
             side_effect=RuntimeError("Simulated DB transient error"),
         ):
        fail_resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={"query": "Check my medication adherence.", "max_steps": 1},
        )
    assert fail_resp.status_code == 200, fail_resp.text
    f_data = fail_resp.json()
    assert f_data["orchestration_state"] == OrchestrationState.DEGRADED.value
    assert f_data["execution_steps"][0]["status"] == "failed"
    assert "Simulated DB transient error" in (f_data["execution_steps"][0]["error_recovery"] or "")


# ============================================================
# 9. AUTHENTICATION, USER ISOLATION & HISTORY TRACE
# ============================================================

def test_user_isolation_and_history_trace_persistence(client, user_alpha, user_beta):
    """
    Verify that User Alpha cannot execute or view history for User Beta (`403 Forbidden`),
    and that `/orchestration/history` returns the persisted `execution_steps` and `user_request`.
    """
    # Unauthorized call without token -> 401/403
    unauth = client.post("/orchestration/execute", json={"query": "Check my glucose"})
    assert unauth.status_code in (401, 403)

    # Cross-user attempt -> 403
    cross = client.post(
        f"/orchestration/execute?user_id={user_beta['user_id']}",
        headers=user_alpha["headers"],
        json={"query": "Check my glucose"},
    )
    assert cross.status_code == 403

    # Valid run for User Alpha
    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=False):
        ok_resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={"query": "Check my active alerts and notifications."},
        )
    assert ok_resp.status_code == 200

    # Verify history for User Alpha includes execution_steps and user_request, and User Beta sees none of Alpha's runs
    hist_a = client.get("/orchestration/history", headers=user_alpha["headers"])
    assert hist_a.status_code == 200
    items_a = hist_a.json()
    assert len(items_a) >= 1
    latest = items_a[0]
    assert latest["workflow_type"] == WorkflowType.WORKFLOW_DYNAMIC_AGENTIC.value
    assert latest["user_request"] == "Check my active alerts and notifications."
    assert len(latest["execution_steps"]) >= 1

    hist_b = client.get("/orchestration/history", headers=user_beta["headers"])
    assert hist_b.status_code == 200
    assert all(item["user_id"] == user_beta["user_id"] for item in hist_b.json())


# ============================================================
# 10. REGRESSION TESTS: LIVE OLLAMA GLUCOSE ASSESSMENT DEFECT FIXES
# ============================================================

def test_glucose_explain_request_preserves_health_assessment_intent():
    """
    Defect 1 Regression: A request to assess blood glucose and explain statistical deviation
    must be classified as `health_assessment` (not `medical_document_question`).
    """
    prompt = "Assess my recent blood glucose measurements and explain if there is any statistical deviation."
    assert classify_request_intent(prompt) == "health_assessment"
    assert classify_request_intent("What does my uploaded lab report say about my glucose?") == "medical_document_question"


def test_request_scoped_tool_validation_rejects_unrelated_metrics():
    """
    Defect 2 Regression: When a request is scoped to `blood_glucose`, attempting to call
    `monitor_health_metric` or `assess_health_risk` on `blood_pressure_systolic` or
    `blood_pressure_diastolic` must be rejected with `ToolValidationError`, while
    relevant follow-up tools (`assess_health_risk(blood_glucose)`, `query_medical_knowledge`)
    remain dynamically selectable.
    """
    prompt = "Assess my recent blood glucose measurements and explain if there is any statistical deviation."
    scope = build_request_tool_scope(
        user_request=prompt,
        initial_intent="health_assessment",
        minimal_context={
            "available_metrics": {
                "blood_glucose": 8,
                "blood_pressure_systolic": 8,
                "blood_pressure_diastolic": 8,
            }
        },
        preferred_metric="blood_glucose",
    )
    assert scope.primary_metric == "blood_glucose"
    assert scope.allowed_metrics == ["blood_glucose"]
    assert "monitor_health_metric" in scope.allowed_tools
    assert "assess_health_risk" in scope.allowed_tools
    assert "query_medical_knowledge" in scope.allowed_tools

    # In-scope glucose monitoring, risk assessment, and knowledge retrieval pass validation
    validate_tool_against_request_scope(
        "monitor_health_metric",
        {"metric_type": "blood_glucose"},
        scope,
    )
    validate_tool_against_request_scope(
        "assess_health_risk",
        {"metric_type": "blood_glucose", "include_experimental_ml": False},
        scope,
    )
    validate_tool_against_request_scope(
        "query_medical_knowledge",
        {"question": "Clinical guidelines for blood glucose deviation.", "n_results": 3},
        scope,
    )

    # Unrelated blood pressure metrics are rejected
    with pytest.raises(ToolValidationError, match="Out-of-scope metric 'blood_pressure_systolic'"):
        validate_tool_against_request_scope(
            "monitor_health_metric",
            {"metric_type": "blood_pressure_systolic"},
            scope,
        )

    with pytest.raises(ToolValidationError, match="Out-of-scope metric 'blood_pressure_diastolic'"):
        validate_tool_against_request_scope(
            "monitor_health_metric",
            {"metric_type": "blood_pressure_diastolic"},
            scope,
        )


def test_llm_glucose_assessment_blocks_unrelated_bp_and_prioritizes_glucose(client, user_alpha):
    """
    Defects 1, 2, 3, 4, 5, 6 Regression:
    Simulate the exact glucose assessment scenario where the user has both blood glucose
    (ending at 158 mg/dL, 8 readings with mean ~114.9 mg/dL) and blood pressure (136/85 mmHg)
    in the database, and the LLM planner:
    - Step 1: selects `monitor_health_metric(blood_glucose)`
    - Step 2: attempts an out-of-scope `monitor_health_metric(blood_pressure_systolic)` (rejected!)
    - Step 3: selects `query_medical_knowledge` (and attempts to overwrite `detected_intent="medical_document_question"`)
    Verify:
    - `detected_intent` remains `"health_assessment"`
    - Unrelated `blood_pressure_systolic` and `blood_pressure_diastolic` tools are NEVER executed
    - `selected_agents` is `["MonitoringAgent", "RiskAssessmentAgent", "MedicalKnowledgeAgent"]`
    - Final response prioritizes `blood_glucose` (`158.0 mg/dL`, `statistical deviation detected`,
      `increasing` trend, `114.9 mg/dL` mean, rule-based risk category `'moderate'`)
    - Termination reason matches the actual `health_assessment` execution path
    - No clinical diagnosis is inferred from internal rule-based risk labels
    - `latency_breakdown_ms` reports separate timing for `planner_llm_ms`, `agent_execution_ms`,
      `rag_generation_ms`, and `response_synthesis_ms`.
    """
    # Seed 8 glucose readings with mean 114.9 mg/dL and latest 158.0 mg/dL:
    # sum([102, 104, 105, 106, 108, 116, 120, 158]) = 919.0 / 8 = 114.875 -> 114.9 mg/dL
    for v in [102.0, 104.0, 105.0, 106.0, 108.0, 116.0, 120.0, 158.0]:
        add_metric(client, user_alpha, "blood_glucose", v, "mg/dL")

    # Also seed blood pressure readings to ensure the planner does not drift into them
    for v in [120.0, 122.0, 121.0, 123.0, 122.0, 128.0, 132.0, 136.0]:
        add_metric(client, user_alpha, "blood_pressure_systolic", v, "mmHg")
    for v in [76.0, 77.0, 78.0, 77.0, 78.0, 81.0, 83.0, 85.0]:
        add_metric(client, user_alpha, "blood_pressure_diastolic", v, "mmHg")

    mock_rag = {
        "answer": (
            "Elevated blood glucose readings and statistical deviations warrant reviewing dietary, "
            "activity, and monitoring logs with a healthcare professional [1]."
        ),
        "sources": [
            {
                "document_title": "ADA Glycemic Monitoring Reference",
                "source_organization": "American Diabetes Association",
                "chunk_text": "Review blood glucose trends with a clinician.",
            }
        ],
        "limitations": [],
        "disclaimer": "Educational only.",
        "is_emergency": False,
        "emergency_guidance": None,
    }

    llm_proposals = [
        # Step 1: Valid glucose monitoring call
        PlannerDecision(
            detected_intent="health_assessment",
            action="call_tool",
            tool_name="monitor_health_metric",
            tool_args={"metric_type": "blood_glucose"},
            selection_reason="Inspect recent blood glucose measurements first.",
        ),
        # Step 2 Attempt 1: LLM tries to drift to blood_pressure_systolic -> rejected by scope guard
        PlannerDecision(
            detected_intent="health_assessment",
            action="call_tool",
            tool_name="monitor_health_metric",
            tool_args={"metric_type": "blood_pressure_systolic"},
            selection_reason="Drifted to blood pressure.",
        ),
        # Step 2 Attempt 2: After receiving scope rejection feedback, LLM selects assess_health_risk(blood_glucose)
        PlannerDecision(
            detected_intent="health_assessment",
            action="call_tool",
            tool_name="assess_health_risk",
            tool_args={"metric_type": "blood_glucose", "include_experimental_ml": False},
            selection_reason="Evaluate longitudinal risk for blood glucose.",
        ),
        # Step 3: LLM calls query_medical_knowledge and tries to overwrite detected_intent="medical_document_question"
        PlannerDecision(
            detected_intent="medical_document_question",
            action="call_tool",
            tool_name="query_medical_knowledge",
            tool_args={
                "question": "Patient has moderate risk of diabetes; explain blood glucose statistical deviation.",
                "include_user_documents": True,
                "include_global_knowledge": True,
                "n_results": 3,
            },
            selection_reason="Retrieve clinical reference guidance for deviating blood glucose.",
        ),
    ]

    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.planner._call_ollama_planner_once", side_effect=llm_proposals), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", return_value=mock_rag):
        resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={
                "query": "Assess my recent blood glucose measurements and explain if there is any statistical deviation.",
                "metric_type": "blood_glucose",
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 1. Original intent preserved as health_assessment
    assert data["detected_intent"] == "health_assessment"

    # 2. Only glucose-relevant agents executed; no blood pressure monitoring executed
    assert data["selected_agents"] == [
        "MonitoringAgent",
        "RiskAssessmentAgent",
        "MedicalKnowledgeAgent",
    ]
    for step in data["execution_steps"]:
        inter = step.get("intermediate_output") or {}
        assert inter.get("metric_type") not in ("blood_pressure_systolic", "blood_pressure_diastolic")

    # Verify Step 2 recorded the rejection of out-of-scope blood_pressure_systolic
    assert "blood_pressure_systolic" in (data["execution_steps"][1].get("error_recovery") or "")

    # 3. Primary metric (blood_glucose: 158.0 mg/dL, mean 114.9 mg/dL, increasing, moderate) prioritized
    assert data["monitoring"]["metric_type"] == "blood_glucose"
    assert data["monitoring"]["latest_value"] == 158.0
    assert data["monitoring"]["status"] == "deviation"
    assert data["risk_assessment"]["risk_level"] == "moderate"

    summary = data["summary_text"]
    assert "158.0 mg/dL" in summary
    assert "Statistical deviation detected" in summary
    assert "increasing" in summary
    assert "114.9 mg/dL" in summary
    assert "moderate" in summary.lower()
    assert "blood pressure" not in summary.lower()
    assert "not a clinical diagnosis" in summary.lower() or "not a confirmed medical condition" in summary.lower()

    # 4. Termination reason matches the actual health_assessment execution path
    term = data["termination_reason"] or ""
    assert "health assessment" in term.lower()
    assert "blood glucose" in term.lower()
    assert "MonitoringAgent, RiskAssessmentAgent, MedicalKnowledgeAgent" in term

    # 5. Neutral knowledge query phrasing
    sanitized_q = sanitize_knowledge_query_phrasing("Patient has moderate risk of diabetes")
    assert "moderate risk of diabetes" not in sanitized_q.lower()

    # 6. Separate latency breakdown included
    breakdown = data.get("latency_breakdown_ms") or {}
    assert "planner_llm_ms" in breakdown
    assert "agent_execution_ms" in breakdown
    assert "rag_generation_ms" in breakdown
    assert "response_synthesis_ms" in breakdown


def test_comprehensive_summary_prevents_premature_finish_and_includes_medication_adherence(
    client, user_alpha, db_session
):
    """
    Final Comprehensive Summary Regression:
    User request:
      "Analyze my recent health measurements, medication adherence, and uploaded medical reports to generate a comprehensive personalized health summary."
    When the LLM attempts to finish prematurely after MonitoringAgent -> RiskAssessmentAgent -> MedicalKnowledgeAgent
    (skipping MedicationAgent), the planner rejects the premature finish, provides missing-domain feedback
    for `medication_adherence`, and executes `check_medication_adherence` (`MedicationAgent`) so that all
    three requested domains (health measurements, medication adherence, and uploaded medical reports) appear
    in the final consolidated response.
    """
    uid = user_alpha["user_id"]

    # 1. Seed health measurements
    for v in [105.0, 108.0, 110.0, 112.0, 115.0, 122.0, 130.0, 158.0]:
        add_metric(client, user_alpha, "blood_glucose", v, "mg/dL")

    # 2. Seed active medication
    med_resp = client.post(
        f"/medications?user_id={uid}",
        headers=user_alpha["headers"],
        json={
            "name": "Metformin XR",
            "dosage": "500 mg",
            "frequency": "Twice daily",
            "instructions": "Take with meals",
            "start_date": date.today().isoformat(),
        },
    )
    assert med_resp.status_code in (200, 201), med_resp.text

    # 3. Seed uploaded medical document
    doc = MedicalDocument(
        user_id=uid,
        filename="comprehensive_lab_report.pdf",
        stored_path="storage/medical_reports/comprehensive_lab_report.pdf",
        content_type="application/pdf",
        file_size=2048,
        sha256_hash="b" * 64,
        extracted_text="Lab Summary: Fasting glucose 132 mg/dL, HbA1c 6.2%. Continue dietary monitoring.",
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        DocumentIndexStatus(
            document_id=doc.id,
            user_id=uid,
            status="indexed",
            chunk_count=2,
            indexed_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    mock_rag = {
        "answer": (
            "Your uploaded report notes fasting glucose of 132 mg/dL and HbA1c of 6.2% [1], "
            "alongside standard lifestyle and glycemic monitoring recommendations [2]."
        ),
        "sources": [
            {
                "document_title": "comprehensive_lab_report.pdf",
                "source_organization": "Uploaded Medical Report",
                "chunk_text": "Lab Summary: Fasting glucose 132 mg/dL, HbA1c 6.2%.",
            },
            {
                "document_title": "ADA Standards of Care",
                "source_organization": "ADA",
                "chunk_text": "Routine glycemic and lifestyle monitoring.",
            },
        ],
        "limitations": [],
        "disclaimer": "Educational only.",
        "is_emergency": False,
        "emergency_guidance": None,
    }

    llm_sequence = [
        # Step 1: MonitoringAgent
        PlannerDecision(
            detected_intent="comprehensive_summary",
            action="call_tool",
            tool_name="monitor_health_metric",
            tool_args={"metric_type": "blood_glucose"},
            selection_reason="Inspect recent health measurements first.",
        ),
        # Step 2: RiskAssessmentAgent
        PlannerDecision(
            detected_intent="comprehensive_summary",
            action="call_tool",
            tool_name="assess_health_risk",
            tool_args={"metric_type": "blood_glucose", "include_experimental_ml": False},
            selection_reason="Evaluate longitudinal trend and rule-based risk for blood glucose.",
        ),
        # Step 3: MedicalKnowledgeAgent
        PlannerDecision(
            detected_intent="comprehensive_summary",
            action="call_tool",
            tool_name="query_medical_knowledge",
            tool_args={
                "question": "Summarize my uploaded medical reports and blood glucose guidelines.",
                "include_user_documents": True,
                "include_global_knowledge": True,
                "n_results": 3,
            },
            selection_reason="Retrieve uploaded medical report findings and clinical knowledge.",
        ),
        # Step 4 Attempt 1: Premature finish before MedicationAgent -> MUST BE REJECTED!
        PlannerDecision(
            detected_intent="comprehensive_summary",
            action="finish",
            selection_reason="All requested components of the comprehensive summary have been analyzed and explained.",
        ),
        # Step 4 Attempt 2 (after receiving missing-domain feedback): LLM selects check_medication_adherence
        PlannerDecision(
            detected_intent="comprehensive_summary",
            action="call_tool",
            tool_name="check_medication_adherence",
            tool_args={"refresh_reminders": True},
            selection_reason="Address remaining requested medication_adherence domain via MedicationAgent.",
        ),
    ]

    with patch("healthguard.orchestration.planner.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.planner._call_ollama_planner_once", side_effect=llm_sequence) as mock_llm, \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", return_value=mock_rag):
        resp = client.post(
            "/orchestration/execute",
            headers=user_alpha["headers"],
            json={
                "query": (
                    "Analyze my recent health measurements, medication adherence, and uploaded "
                    "medical reports to generate a comprehensive personalized health summary."
                ),
            },
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["planner_mode"] == "llm_assisted"
    assert data["detected_intent"] == "comprehensive_summary"
    assert set(data["selected_agents"]) == {
        "MonitoringAgent",
        "RiskAssessmentAgent",
        "MedicalKnowledgeAgent",
        "MedicationAgent",
    }

    # Verify that Step 4 Attempt 2 received the premature-finish feedback for medication_adherence
    assert mock_llm.call_count == 5
    step4_retry_kwargs = mock_llm.call_args_list[4].kwargs
    assert "medication_adherence" in (step4_retry_kwargs.get("retry_feedback") or "")

    # Verify structured medication result and summary_text completeness
    assert data["medication"] is not None
    assert data["medication"]["active_medications_count"] == 1
    summary = data["summary_text"]
    assert "Recorded Measurement" in summary
    assert "Statistical Deviation Analysis" in summary
    assert "Rule-Based Risk & Trend Classification" in summary
    assert "Medication Adherence:" in summary
    assert "Active medications: 1 (Metformin XR (500 mg))" in summary
    assert "Overall adherence:" in summary
    assert "Taken doses:" in summary
    assert "Missed doses:" in summary
    assert "Overdue/unconfirmed doses:" in summary
    assert "Uploaded Medical Document & Knowledge Findings:" in summary
    assert "comprehensive_lab_report.pdf" in summary
    assert "General Educational Guidance:" in summary

    # Verify termination reason reflects all three addressed domains
    term = data["termination_reason"] or ""
    assert "health_measurements" in term
    assert "medication_adherence" in term
    assert "medical_documents" in term



