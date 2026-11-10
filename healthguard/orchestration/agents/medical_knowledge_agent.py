"""
Medical Knowledge Agent — Phase 8

Retrieves verified medical knowledge through the Phase 7 RAG pipeline.
Provides verifiable source references with citations.
Gracefully degrades when ChromaDB or Ollama is unavailable.
Never fabricates clinical evidence.
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session

from healthguard.rag.rag_pipeline import run_rag_pipeline
from healthguard.rag.llm_service import check_ollama_available
from healthguard.orchestration.schemas import (
    MedicalCitation,
    MedicalKnowledgeAgentResult,
)

logger = logging.getLogger(__name__)


class MedicalKnowledgeAgent:
    """Agent responsible for grounded medical knowledge retrieval and explanations."""

    def __init__(self, db: Session):
        self.db = db

    def query_knowledge(
        self,
        user_id: int,
        question: str,
        n_results: int = 3,
        include_user_documents: bool = True,
        include_global_knowledge: bool = True,
    ) -> MedicalKnowledgeAgentResult:
        """
        Execute grounded RAG retrieval for clinical guidance with graceful degradation.
        """
        if not question or not question.strip():
            return MedicalKnowledgeAgentResult(
                status="skipped",
                query="",
                explanation="No medical query provided for knowledge retrieval.",
                citations=[],
            )

        clean_question = question.strip()

        # Check Ollama availability before running RAG to support graceful degradation
        try:
            ollama_online = check_ollama_available()
        except Exception:
            ollama_online = False

        try:
            rag_output = run_rag_pipeline(
                db=self.db,
                user_id=user_id,
                question=clean_question,
                n_results=n_results,
                include_user_documents=include_user_documents,
                include_global_knowledge=include_global_knowledge,
            )

            citations: list[MedicalCitation] = []
            for src in rag_output.get("sources", []):
                citations.append(
                    MedicalCitation(
                        title=src.get("title", "Clinical Reference Document"),
                        source_organization=src.get("source_organization", "Health Authority"),
                        source_url=src.get("source_url"),
                        excerpt=src.get("chunk_text", "")[:300],
                    )
                )

            is_emergency = rag_output.get("is_emergency", False)
            guidance = rag_output.get("emergency_guidance")
            limitations = rag_output.get("limitations", [])

            status = "degraded" if not ollama_online else "success"

            return MedicalKnowledgeAgentResult(
                status=status,
                query=clean_question,
                explanation=rag_output.get("answer", "No response generated."),
                citations=citations,
                limitations=limitations,
                is_emergency=is_emergency,
                emergency_guidance=guidance,
            )

        except Exception as exc:
            logger.warning("RAG pipeline graceful degradation triggered: %s", exc)
            fallback_explanation = (
                "Verified medical knowledge retrieval is temporarily operating in degraded mode "
                "(vector database or inference service offline). "
                "For health questions regarding vital measurements or medications, please consult "
                "standard clinical guidelines and your healthcare provider."
            )
            return MedicalKnowledgeAgentResult(
                status="degraded",
                query=clean_question,
                explanation=fallback_explanation,
                citations=[],
                limitations=[f"Retrieval degraded: {str(exc)}"],
                is_emergency=False,
            )
