"""
RAG Pipeline — Phase 7

Orchestrates the full RAG workflow:
1. Classify query intent
2. Safety check
3. Retrieve from appropriate sources
4. Build personal context (deterministic, no LLM)
5. Generate answer with Ollama
6. Validate response safety
7. Return structured result

Personal health context is built from actual backend data, not invented.
LLM is used only for language generation, not for calculations.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from healthguard.database.models import Medication, MedicationDoseOccurrence, HealthMetric
from healthguard.rag.retriever import (
    retrieve_from_global_knowledge,
    retrieve_from_user_documents,
    classify_query_intent,
)
from healthguard.rag.llm_service import generate_answer, check_ollama_available
from healthguard.rag.safety import (
    check_unsafe_request,
    validate_response,
    sanitize_retrieved_context,
    DISCLAIMER,
    EMERGENCY_GUIDANCE,
)
from healthguard.services.medication_adherence import (
    get_medication_adherence_summary,
    get_medication_timeline,
)

logger = logging.getLogger(__name__)


def _build_personal_health_context(
    db: Session,
    user_id: int,
    intent: dict,
) -> Optional[str]:
    """
    Build a personal health context string from actual database records.

    Uses deterministic backend logic, not LLM, for calculations.
    Returns None if no personal data is relevant.
    """
    parts = []
    now = datetime.utcnow()

    if intent.get("needs_personal_history"):
        # Last 30 days of health metrics
        thirty_days_ago = now - timedelta(days=30)
        metrics = (
            db.query(HealthMetric)
            .filter(
                HealthMetric.user_id == user_id,
                HealthMetric.recorded_at >= thirty_days_ago,
            )
            .order_by(HealthMetric.recorded_at.desc())
            .limit(50)
            .all()
        )

        if metrics:
            by_type: dict[str, list] = {}
            for m in metrics:
                by_type.setdefault(m.metric_type, []).append(m)

            parts.append("HEALTH METRICS (last 30 days, most recent first):")
            for metric_type, readings in by_type.items():
                values = [r.value for r in readings]
                avg = round(sum(values) / len(values), 2)
                latest = readings[0]
                unit = readings[0].unit
                parts.append(
                    f"  {metric_type.replace('_', ' ').title()}: "
                    f"latest={latest.value} {unit}, "
                    f"avg={avg} {unit}, "
                    f"count={len(readings)}, "
                    f"range=[{min(values)}, {max(values)}] {unit}"
                )

    if intent.get("needs_medication_info"):
        # Active medications with adherence
        active_meds = (
            db.query(Medication)
            .filter(
                Medication.user_id == user_id,
                Medication.is_active.is_(True),
            )
            .all()
        )

        if active_meds:
            parts.append("\nACTIVE MEDICATIONS AND ADHERENCE:")
            for med in active_meds:
                adherence = get_medication_adherence_summary(db, med, now)
                overall = adherence["overall"]
                pct = overall.get("adherence_percentage")
                pct_str = f"{pct}%" if pct is not None else "No scheduled doses yet"
                parts.append(
                    f"  {med.name} ({med.dosage}): "
                    f"adherence={pct_str}, "
                    f"taken={overall['taken']}, "
                    f"overdue={overall['overdue_unconfirmed']}"
                )

    return "\n".join(parts) if parts else None


def run_rag_pipeline(
    db: Session,
    user_id: int,
    question: str,
    n_results: int = 5,
    include_user_documents: bool = True,
    include_global_knowledge: bool = True,
    document_id: Optional[int] = None,
) -> dict:
    """
    Full RAG pipeline execution.

    Parameters:
        db: Database session.
        user_id: Authenticated user's ID.
        question: User's question.
        n_results: Number of chunks to retrieve from each source.
        include_user_documents: Whether to search user's private documents.
        include_global_knowledge: Whether to search global knowledge base.
        document_id: If set, restricts user document search to this document.

    Returns:
        dict with answer, sources, limitations, disclaimer, and optional error.
    """
    # 1. Safety check
    safety_result = check_unsafe_request(question)

    if not safety_result["safe_to_process"]:
        return {
            "answer": safety_result["reason"],
            "sources": [],
            "limitations": ["Safety check: request not processed"],
            "disclaimer": DISCLAIMER,
            "is_emergency": safety_result["is_emergency"],
            "emergency_guidance": safety_result["emergency_guidance"],
        }

    response_prefix = ""
    if safety_result["is_emergency"]:
        response_prefix = EMERGENCY_GUIDANCE + "\n\n"

    # 2. Classify intent
    intent = classify_query_intent(question)

    # 3. Retrieve relevant chunks
    all_chunks: list[dict] = []

    if include_global_knowledge and intent.get("needs_general_knowledge"):
        global_chunks = retrieve_from_global_knowledge(question, n_results=n_results)
        for chunk in global_chunks:
            chunk["_source_type"] = "global_knowledge"
        all_chunks.extend(global_chunks)

    if include_user_documents and (
        intent.get("needs_user_documents")
        or intent.get("needs_personal_history")
        or document_id is not None
    ):
        user_chunks = retrieve_from_user_documents(
            user_id=user_id,
            query=question,
            n_results=n_results,
            document_id=document_id,
        )
        for chunk in user_chunks:
            chunk["_source_type"] = "user_document"
        all_chunks.extend(user_chunks)

    # 4. Sanitize retrieved content (prompt injection protection)
    all_chunks = sanitize_retrieved_context(all_chunks)

    # 5. Build personal context using deterministic backend logic
    personal_context = None
    if intent.get("needs_personal_history") or intent.get("needs_medication_info"):
        personal_context = _build_personal_health_context(db, user_id, intent)

    # 6. Generate answer
    llm_result = generate_answer(
        question=question,
        context_chunks=all_chunks,
        personal_context=personal_context,
    )

    if llm_result.get("error"):
        return {
            "answer": None,
            "error": llm_result["error"],
            "sources": llm_result.get("sources", []),
            "limitations": llm_result.get("limitations", []),
            "disclaimer": DISCLAIMER,
            "is_emergency": safety_result["is_emergency"],
            "emergency_guidance": safety_result["emergency_guidance"],
            "chunks_retrieved": len(all_chunks),
            "intent": intent,
        }

    # 7. Validate response
    answer_text = llm_result.get("answer", "")
    validation = validate_response(answer_text)
    final_answer = response_prefix + validation["sanitized"]

    limitations = llm_result.get("limitations", [])
    if not validation["is_safe"]:
        limitations.append("Response contains content flagged for review.")

    return {
        "answer": final_answer,
        "sources": llm_result.get("sources", []),
        "limitations": limitations,
        "disclaimer": DISCLAIMER,
        "is_emergency": safety_result["is_emergency"],
        "emergency_guidance": safety_result["emergency_guidance"],
        "model_used": llm_result.get("model_used"),
        "chunks_retrieved": len(all_chunks),
        "intent": intent,
    }
