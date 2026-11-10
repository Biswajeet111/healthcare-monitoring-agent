"""
Test suite for Phase 8: Agentic AI Orchestration

Covers:
- Agent coordination & structured outputs
- Workflow A: New health measurement assessment
- Workflow B: Medication adherence check
- Workflow C: Consolidated health summaries
- Workflow D: Safety escalation for critical physiological metrics
- Idempotency and duplicate prevention
- Authentication and strict user isolation
- Graceful degradation on RAG/Ollama/ChromaDB offline
- Agent execution history auditing
- Safety controls (no autonomous diagnoses or prescriptions)
"""

from datetime import date, datetime
from unittest.mock import patch
import pytest

from healthguard.database.session import get_db
from healthguard.main import app
from healthguard.orchestration.agents.monitoring_agent import MonitoringAgent
from healthguard.orchestration.agents.risk_assessment_agent import RiskAssessmentAgent
from healthguard.orchestration.agents.medication_agent import MedicationAgent
from healthguard.orchestration.agents.medical_knowledge_agent import MedicalKnowledgeAgent
from healthguard.orchestration.agents.notification_agent import NotificationAgent
from healthguard.orchestration.orchestrator import AgenticOrchestrator
from healthguard.orchestration.schemas import (
    OrchestrationState,
    WorkflowType,
    RiskLevel,
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
def auth_user_a(client):
    reg = client.post(
        "/auth/register",
        json={
            "full_name": "Patient Alpha",
            "email": "patient.alpha@example.com",
            "password": "PasswordAlpha@123",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]

    login = client.post(
        "/auth/login",
        json={
            "email": "patient.alpha@example.com",
            "password": "PasswordAlpha@123",
        },
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    return {
        "user_id": user_id,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
def auth_user_b(client):
    reg = client.post(
        "/auth/register",
        json={
            "full_name": "Patient Beta",
            "email": "patient.beta@example.com",
            "password": "PasswordBeta@123",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    user_id = reg.json()["id"]

    login = client.post(
        "/auth/login",
        json={
            "email": "patient.beta@example.com",
            "password": "PasswordBeta@123",
        },
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    return {
        "user_id": user_id,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def add_test_metric(client, user, metric_type, value, unit="mg/dL"):
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
# UNIT TESTS: SPECIALIZED AGENTS
# ============================================================

def test_monitoring_agent_normal_and_deviation(client, auth_user_a, db_session):
    user_id = auth_user_a["user_id"]
    for v in [90.0, 92.0, 91.0, 93.0, 90.0, 92.0, 91.0, 93.0]:
        add_test_metric(client, auth_user_a, "blood_glucose", v, "mg/dL")

    agent = MonitoringAgent(db_session)
    res = agent.analyze_metrics(user_id=user_id, metric_type="blood_glucose")
    assert res.metric_type == "blood_glucose"
    assert res.status in ("normal", "deviation", "insufficient_data")
    assert res.disclaimer is not None
    assert not res.is_urgent


def test_monitoring_agent_critical_physiological_value(client, auth_user_a, db_session):
    user_id = auth_user_a["user_id"]
    add_test_metric(client, auth_user_a, "blood_pressure_systolic", 195.0, "mmHg")

    agent = MonitoringAgent(db_session)
    res = agent.analyze_metrics(user_id=user_id, metric_type="blood_pressure_systolic")
    assert res.is_urgent is True
    assert res.status == "urgent_review"
    assert "hypertensive crisis" in res.urgent_reason.lower()


def test_risk_assessment_agent_separates_ml_from_rules(client, auth_user_a, db_session):
    user_id = auth_user_a["user_id"]
    for v in [120, 125, 130, 135]:
        add_test_metric(client, auth_user_a, "blood_glucose", v, "mg/dL")

    agent = RiskAssessmentAgent(db_session)
    # Without ML
    res1 = agent.evaluate_risk(user_id=user_id, metric_type="blood_glucose")
    assert len(res1.rule_based_findings) > 0
    assert len(res1.experimental_ml_estimates) == 0
    assert "medical diagnosis" in res1.disclaimer.lower()

    # With experimental ML features
    ml_features = {
        "Pregnancies": 1,
        "Glucose": 140,
        "BloodPressure": 80,
        "SkinThickness": 20,
        "Insulin": 85,
        "BMI": 28.5,
        "DiabetesPedigreeFunction": 0.45,
        "Age": 35,
    }
    res2 = agent.evaluate_risk(
        user_id=user_id,
        metric_type="blood_glucose",
        experimental_ml=True,
        ml_features=ml_features,
    )
    assert len(res2.experimental_ml_estimates) == 1
    est = res2.experimental_ml_estimates[0]
    assert est.get("is_medical_diagnosis") is False
    assert "disclaimer" in est


def test_medication_agent_no_autonomous_modifications(client, auth_user_a, db_session):
    user_id = auth_user_a["user_id"]
    agent = MedicationAgent(db_session)
    res = agent.evaluate_medications(user_id=user_id)
    assert "never modifies medication schedules" in res.disclaimer


def test_medical_knowledge_agent_graceful_degradation(client, auth_user_a, db_session):
    user_id = auth_user_a["user_id"]
    agent = MedicalKnowledgeAgent(db_session)
    # Force exception to test graceful degradation
    with patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", side_effect=RuntimeError("VectorStore offline")):
        res = agent.query_knowledge(user_id=user_id, question="What is normal blood glucose?")
        assert res.status == "degraded"
        assert "degraded mode" in res.explanation
        assert len(res.limitations) > 0


def test_medical_knowledge_agent_unavailable_ollama(client, auth_user_a, db_session):
    """When Ollama is unavailable, run_rag_pipeline returns answer=None and an error string."""
    user_id = auth_user_a["user_id"]
    agent = MedicalKnowledgeAgent(db_session)

    mock_rag_output = {
        "answer": None,
        "error": (
            "The local AI service (Ollama) is not available. "
            "Please ensure Ollama is running and the model 'llama3.1' is installed."
        ),
        "sources": [],
        "limitations": ["Local LLM unavailable."],
        "disclaimer": "Educational only.",
        "is_emergency": False,
        "emergency_guidance": None,
    }
    with patch("healthguard.orchestration.agents.medical_knowledge_agent.check_ollama_available", return_value=False), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", return_value=mock_rag_output):
        res = agent.query_knowledge(user_id=user_id, question="What is normal blood glucose?")
        assert res.status == "degraded"
        assert isinstance(res.explanation, str) and len(res.explanation) > 0
        assert "degraded mode" in res.explanation
        assert "Ollama" in res.explanation
        assert any("unavailable" in lim.lower() for lim in res.limitations)


def test_medical_knowledge_agent_ollama_http_500_error(client, auth_user_a, db_session):
    """
    Regression test: When check_ollama_available() succeeds (/api/tags -> 200),
    but /api/chat fails with HTTP 500 (e.g. model load / memory error),
    generate_answer() and MedicalKnowledgeAgent must:
    - Not raise a Pydantic ValidationError for explanation=None
    - Report status='degraded' (never 'success')
    - Preserve the HTTP 500 error details and any retrieved citations
    """
    import httpx
    from healthguard.rag.llm_service import generate_answer

    fake_request = httpx.Request("POST", "http://localhost:11434/api/chat")
    fake_response = httpx.Response(
        500,
        request=fake_request,
        json={"error": "model requires more system memory (4.8 GiB) than is available (3.1 GiB)"},
    )

    chunks = [
        {
            "id": "knowledge-doc-2-chunk-0",
            "text": "Normal fasting blood glucose is below 100 mg/dL.",
            "metadata": {
                "title": "Guidance on Global Monitoring for Diabetes",
                "source_organization": "WHO",
                "source_url": "https://www.who.int",
            },
            "distance": 0.25,
        }
    ]

    with patch("healthguard.rag.llm_service.check_ollama_available", return_value=True), \
         patch("healthguard.rag.llm_service.httpx.post", return_value=fake_response):
        llm_out = generate_answer(question="What is normal blood glucose?", context_chunks=chunks)
        assert llm_out["answer"] is None
        assert "500" in llm_out["error"]
        assert "memory" in llm_out["error"]
        assert len(llm_out["sources"]) == 1
        assert llm_out["sources"][0]["document_title"] == "Guidance on Global Monitoring for Diabetes"

    user_id = auth_user_a["user_id"]
    agent = MedicalKnowledgeAgent(db_session)
    with patch("healthguard.orchestration.agents.medical_knowledge_agent.check_ollama_available", return_value=True), \
         patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", return_value={
             **llm_out,
             "is_emergency": False,
             "emergency_guidance": None,
         }):
        res = agent.query_knowledge(user_id=user_id, question="What is normal blood glucose?")
        assert res.status == "degraded"
        assert isinstance(res.explanation, str) and len(res.explanation) > 0
        assert "500" in res.explanation
        assert len(res.citations) == 1
        assert res.citations[0].title == "Guidance on Global Monitoring for Diabetes"


def test_medical_knowledge_agent_missing_or_empty_explanation(client, auth_user_a, db_session):
    """Regression test: missing/None/whitespace-only answer without an explicit error still gets a valid fallback string and degraded status."""
    user_id = auth_user_a["user_id"]
    agent = MedicalKnowledgeAgent(db_session)

    for empty_val in (None, "", "   "):
        with patch("healthguard.orchestration.agents.medical_knowledge_agent.check_ollama_available", return_value=True), \
             patch("healthguard.orchestration.agents.medical_knowledge_agent.run_rag_pipeline", return_value={
                 "answer": empty_val,
                 "sources": [],
                 "limitations": [],
                 "is_emergency": False,
                 "emergency_guidance": None,
             }):
            res = agent.query_knowledge(user_id=user_id, question="Explain HbA1c.")
            assert res.status == "degraded"
            assert isinstance(res.explanation, str) and len(res.explanation.strip()) > 0
            assert "degraded mode" in res.explanation
            assert len(res.limitations) >= 1


# ============================================================
# END-TO-END WORKFLOW INTEGRATION TESTS VIA API
# ============================================================

def test_api_workflow_a_assess(client, auth_user_a):
    user_id = auth_user_a["user_id"]
    for v in [95, 96, 98, 97, 96, 95, 97, 98]:
        add_test_metric(client, auth_user_a, "blood_glucose", v, "mg/dL")

    resp = client.post(
        f"/orchestration/assess?user_id={user_id}",
        headers=auth_user_a["headers"],
        json={
            "metric_type": "blood_glucose",
            "include_knowledge": False,  # fast test without RAG
            "include_adherence": True,
            "experimental_ml": False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user_id"] == user_id
    assert data["workflow_type"] == WorkflowType.WORKFLOW_A_NEW_MEASUREMENT.value
    assert data["orchestration_state"] == OrchestrationState.COMPLETED.value
    assert data["monitoring"] is not None
    assert data["risk_assessment"] is not None
    assert len(data["execution_steps"]) >= 2
    assert "disclaimer" in data


def test_api_workflow_b_medication_check(client, auth_user_a):
    user_id = auth_user_a["user_id"]

    # Create a medication first with valid date format and query param
    med_resp = client.post(
        f"/medications?user_id={user_id}",
        headers=auth_user_a["headers"],
        json={
            "name": "Metformin",
            "dosage": "500mg",
            "frequency": "daily",
            "instructions": "With evening meal",
            "start_date": "2026-11-10",
        },
    )
    assert med_resp.status_code in (200, 201), med_resp.text

    resp = client.post(
        f"/orchestration/medication-check?user_id={user_id}",
        headers=auth_user_a["headers"],
        json={"force_refresh": True},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["workflow_type"] == WorkflowType.WORKFLOW_B_MEDICATION_ADHERENCE.value
    assert data["medication"]["active_medications_count"] >= 1
    assert data["orchestration_state"] == OrchestrationState.COMPLETED.value


def test_api_workflow_c_summary(client, auth_user_a):
    user_id = auth_user_a["user_id"]
    add_test_metric(client, auth_user_a, "blood_glucose", 102.0, "mg/dL")

    resp = client.get(
        f"/orchestration/summary?user_id={user_id}&primary_metric=blood_glucose",
        headers=auth_user_a["headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["workflow_type"] == WorkflowType.WORKFLOW_C_HEALTH_SUMMARY.value
    assert data["monitoring"] is not None
    assert data["medication"] is not None
    assert data["risk_assessment"] is not None
    assert "summary_text" in data


def test_workflow_d_safety_escalation_on_critical_metric(client, auth_user_a):
    user_id = auth_user_a["user_id"]
    # Record a critically high blood glucose reading (> 300 mg/dL)
    add_test_metric(client, auth_user_a, "blood_glucose", 350.0, "mg/dL")

    resp = client.post(
        f"/orchestration/assess?user_id={user_id}",
        headers=auth_user_a["headers"],
        json={
            "metric_type": "blood_glucose",
            "include_knowledge": False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["orchestration_state"] == OrchestrationState.ESCALATED.value
    assert data["safety_escalation"] is not None
    assert "hyperglycemia" in data["safety_escalation"]["urgent_reason"].lower()
    # Confirm safety guidance is present
    assert "immediate" in data["safety_escalation"]["guidance"].lower()
    # Confirm system disclaimer prohibits autonomous prescription or diagnosis
    assert "not an emergency service" in data["safety_escalation"]["disclaimer"].lower()


def test_idempotency_and_caching(client, auth_user_a):
    user_id = auth_user_a["user_id"]
    payload = {
        "metric_type": "blood_glucose",
        "include_knowledge": False,
    }

    # First call
    r1 = client.post(
        f"/orchestration/assess?user_id={user_id}",
        headers=auth_user_a["headers"],
        json=payload,
    )
    assert r1.status_code == 200
    gen1 = r1.json()["generated_at"]

    # Immediate second call within cooldown returns cached result
    r2 = client.post(
        f"/orchestration/assess?user_id={user_id}",
        headers=auth_user_a["headers"],
        json=payload,
    )
    assert r2.status_code == 200
    gen2 = r2.json()["generated_at"]
    assert gen1 == gen2  # cached response timestamp matches


def test_user_isolation_and_security(client, auth_user_a, auth_user_b):
    user_a_id = auth_user_a["user_id"]
    user_b_id = auth_user_b["user_id"]

    # 1. Unauthenticated request rejected
    unauth = client.get(f"/orchestration/summary?user_id={user_a_id}")
    assert unauth.status_code == 401

    # 2. Patient B cannot access Patient A's orchestration summary
    cross_access = client.get(
        f"/orchestration/summary?user_id={user_a_id}",
        headers=auth_user_b["headers"],
    )
    assert cross_access.status_code == 403

    # 3. Patient B cannot trigger assessment on Patient A's profile
    cross_assess = client.post(
        f"/orchestration/assess?user_id={user_a_id}",
        headers=auth_user_b["headers"],
        json={"metric_type": "blood_glucose"},
    )
    assert cross_assess.status_code == 403


def test_agent_execution_history_and_alerts_api(client, auth_user_a):
    user_id = auth_user_a["user_id"]

    # Run an assessment to generate audit history
    client.post(
        f"/orchestration/assess?user_id={user_id}",
        headers=auth_user_a["headers"],
        json={"metric_type": "blood_glucose", "include_knowledge": False},
    )

    # Check history endpoint
    hist_resp = client.get(
        f"/orchestration/history?user_id={user_id}",
        headers=auth_user_a["headers"],
    )
    assert hist_resp.status_code == 200, hist_resp.text
    history = hist_resp.json()
    assert len(history) >= 1
    assert history[0]["user_id"] == user_id
    assert history[0]["status"] in ("completed", "escalated", "degraded")

    # Check alerts endpoint
    alerts_resp = client.get(
        f"/orchestration/alerts?user_id={user_id}",
        headers=auth_user_a["headers"],
    )
    assert alerts_resp.status_code == 200, alerts_resp.text
    alerts = alerts_resp.json()
    assert "unread_monitoring_events" in alerts
    assert "pending_medication_reminders" in alerts
    assert "recent_safety_escalations" in alerts
