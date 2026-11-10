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


DEFAULT_DEGRADED_EXPLANATION = (
    "Verified medical knowledge retrieval is temporarily operating in degraded mode "
    "(local LLM generation unavailable or returned an error). "
    "For health questions regarding vital measurements or medications, please consult "
    "standard clinical guidelines and your healthcare provider."
)


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
            for src in rag_output.get("sources") or []:
                title = (
                    src.get("document_title")
                    or src.get("title")
                    or "Clinical Reference Document"
                )
                citations.append(
                    MedicalCitation(
                        title=title,
                        source_organization=src.get("source_organization") or "Health Authority",
                        source_url=src.get("source_url"),
                        excerpt=(src.get("chunk_text") or src.get("excerpt") or "")[:300],
                    )
                )

            is_emergency = bool(rag_output.get("is_emergency", False))
            guidance = rag_output.get("emergency_guidance")
            limitations = list(rag_output.get("limitations") or [])
            raw_error = rag_output.get("error")
            raw_answer = rag_output.get("answer")
            clean_answer = raw_answer.strip() if isinstance(raw_answer, str) else ""

            # Preserve distinction between:
            # 1. Successful generation (non-empty answer, no error, Ollama online)
            # 2. Degraded / fallback execution (Ollama offline, HTTP 500/timeout, or empty/None answer)
            if raw_error or not ollama_online or not clean_answer:
                status = "degraded"
                if raw_error and not any(raw_error in lim for lim in limitations):
                    limitations.append(str(raw_error))
                elif not clean_answer and not raw_error:
                    limitations.append("No explanation text was returned by the language model.")

                if clean_answer:
                    explanation = clean_answer
                elif raw_error:
                    explanation = (
                        f"{DEFAULT_DEGRADED_EXPLANATION} "
                        f"(Reason: {raw_error})"
                    )
                else:
                    explanation = DEFAULT_DEGRADED_EXPLANATION
            else:
                status = "success"
                explanation = clean_answer

            return MedicalKnowledgeAgentResult(
                status=status,
                query=clean_question,
                explanation=explanation,
                citations=citations,
                limitations=limitations,
                is_emergency=is_emergency,
                emergency_guidance=guidance,
            )

        except Exception as exc:
            logger.warning("RAG pipeline graceful degradation triggered: %s", exc)
            return MedicalKnowledgeAgentResult(
                status="degraded",
                query=clean_question,
                explanation=DEFAULT_DEGRADED_EXPLANATION,
                citations=[],
                limitations=[f"Retrieval degraded: {str(exc)}"],
                is_emergency=False,
            )
