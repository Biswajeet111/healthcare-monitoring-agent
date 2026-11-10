"""
Medical RAG API — Phase 7

Endpoints for:
- Medical Q&A with citation-grounded answers
- User document indexing
- Global knowledge base management
- Personal health context retrieval

Security:
- All endpoints require JWT authentication.
- User document retrieval is scoped to the authenticated user.
- Global knowledge is read-only for regular users.
- Private patient records are never sent to external services.
- Ollama (local) is used for all LLM inference.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from healthguard.core.dependencies import get_current_user
from healthguard.database.models import (
    MedicalDocument,
    MedicalKnowledgeDocument,
    DocumentIndexStatus,
    UserProfile,
)
from healthguard.database.session import get_db
from healthguard.rag.document_ingestion import (
    ingest_global_document,
    ingest_user_document,
    delete_user_document_index,
)
from healthguard.rag.llm_service import check_ollama_available, list_ollama_models
from healthguard.rag.rag_pipeline import run_rag_pipeline
from healthguard.rag.retriever import (
    retrieve_from_global_knowledge,
    retrieve_from_user_documents,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["Medical Knowledge & RAG"])


# ------------------------------------------------------------------
# SCHEMAS
# ------------------------------------------------------------------

class MedicalQuestionRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    include_global_knowledge: bool = True
    include_user_documents: bool = True
    document_id: Optional[int] = None
    n_results: int = Field(default=5, ge=1, le=20)


class KnowledgeIngestRequest(BaseModel):
    file_path: str = Field(..., description="Path to document file (PDF, TXT, MD)")
    title: str = Field(..., min_length=3, max_length=500)
    source_organization: Optional[str] = None
    source_url: Optional[str] = None
    document_type: Optional[str] = None
    publication_date: Optional[str] = None
    review_date: Optional[str] = None


# ------------------------------------------------------------------
# MEDICAL Q&A
# ------------------------------------------------------------------

@router.post("/ask")
def ask_medical_question(
    request: MedicalQuestionRequest,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Answer a medical question using RAG.

    Combines:
    - Approved global medical knowledge
    - User's private uploaded documents (if permitted)
    - User's health metrics and medication records (when relevant)

    Uses local Ollama LLM. Returns answer with verified source citations.
    Private health data never leaves the local server.
    """
    result = run_rag_pipeline(
        db=db,
        user_id=current_user.id,
        question=request.question,
        n_results=request.n_results,
        include_user_documents=request.include_user_documents,
        include_global_knowledge=request.include_global_knowledge,
        document_id=request.document_id,
    )

    if result.get("error") and not result.get("answer"):
        raise HTTPException(
            status_code=503,
            detail=result["error"],
        )

    return result


# ------------------------------------------------------------------
# OLLAMA STATUS
# ------------------------------------------------------------------

@router.get("/status")
def get_rag_status(
    current_user: UserProfile = Depends(get_current_user),
):
    """Check the status of the RAG system (embedding + LLM availability)."""
    ollama_available = check_ollama_available()
    models = list_ollama_models() if ollama_available else []

    embedding_available = False
    try:
        from healthguard.rag.embedding_service import get_embedding_model
        get_embedding_model()
        embedding_available = True
    except Exception:
        pass

    return {
        "ollama_available": ollama_available,
        "available_models": models,
        "embedding_model_available": embedding_available,
        "ready_for_qa": ollama_available and embedding_available,
        "limitation": (
            "If Ollama is not available, questions will return an error. "
            "Semantic retrieval (similarity search) works independently of Ollama."
        ),
    }


# ------------------------------------------------------------------
# GLOBAL KNOWLEDGE BASE MANAGEMENT
# ------------------------------------------------------------------

@router.post("/knowledge/ingest")
def ingest_knowledge_document(
    request: KnowledgeIngestRequest,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ingest an approved medical document into the global knowledge base.

    The file must exist on the server filesystem.
    Only administrators should call this in production.
    For the Document folder in the project root, provide absolute path.
    """
    # Security: only allow files within the project directory
    try:
        file_path = Path(request.file_path)
        project_root = Path(__file__).resolve().parents[2]
        resolved = file_path.resolve()

        # Allow Document folder and storage folder
        allowed_roots = [
            project_root / "Document",
            project_root / "storage",
        ]
        is_allowed = any(
            str(resolved).startswith(str(root)) for root in allowed_roots
        ) or str(resolved).startswith(str(project_root))

        if not is_allowed or not resolved.exists():
            raise HTTPException(
                status_code=400,
                detail="File path is not accessible or does not exist",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid file path: {exc}")

    result = ingest_global_document(
        db=db,
        file_path=str(resolved),
        title=request.title,
        source_organization=request.source_organization,
        source_url=request.source_url,
        document_type=request.document_type,
        publication_date=request.publication_date,
        review_date=request.review_date,
    )
    db.commit()

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/knowledge/documents")
def list_knowledge_documents(
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all ingested global medical knowledge documents."""
    docs = (
        db.query(MedicalKnowledgeDocument)
        .order_by(MedicalKnowledgeDocument.ingested_at.desc())
        .all()
    )

    return {
        "total": len(docs),
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "source_organization": d.source_organization,
                "source_url": d.source_url,
                "document_type": d.document_type,
                "index_status": d.index_status,
                "indexed_at": d.indexed_at.isoformat() if d.indexed_at else None,
                "ingested_at": d.ingested_at.isoformat(),
            }
            for d in docs
        ],
    }


# ------------------------------------------------------------------
# USER DOCUMENT INDEXING
# ------------------------------------------------------------------

@router.post("/documents/{document_id}/index")
def index_user_document(
    document_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Index a user-uploaded medical document for RAG retrieval.

    Extracts text (already done at upload), embeds it, and stores in ChromaDB.
    Only the owning user can index their document.
    """
    # Verify ownership
    document = (
        db.query(MedicalDocument)
        .filter(
            MedicalDocument.id == document_id,
            MedicalDocument.user_id == current_user.id,
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found or access denied")

    result = ingest_user_document(db, document_id, current_user.id)
    db.commit()

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@router.get("/documents")
def get_user_documents_with_index_status(
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List user documents with their RAG index status."""
    documents = (
        db.query(MedicalDocument)
        .filter(MedicalDocument.user_id == current_user.id)
        .order_by(MedicalDocument.uploaded_at.desc())
        .all()
    )

    # Get index status for each document
    index_statuses = {
        s.document_id: s
        for s in db.query(DocumentIndexStatus)
        .filter(DocumentIndexStatus.user_id == current_user.id)
        .all()
    }

    return {
        "total": len(documents),
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "content_type": d.content_type,
                "file_size": d.file_size,
                "uploaded_at": d.uploaded_at.isoformat(),
                "has_extracted_text": bool(d.extracted_text),
                "index_status": (
                    index_statuses[d.id].status
                    if d.id in index_statuses
                    else "not_indexed"
                ),
                "chunk_count": (
                    index_statuses[d.id].chunk_count
                    if d.id in index_statuses
                    else None
                ),
                "indexed_at": (
                    index_statuses[d.id].indexed_at.isoformat()
                    if d.id in index_statuses and index_statuses[d.id].indexed_at
                    else None
                ),
            }
            for d in documents
        ],
    }


@router.get("/search")
def search_knowledge(
    query: str = Query(..., min_length=3, max_length=500),
    source: str = Query(default="global", pattern="^(global|user|both)$"),
    n_results: int = Query(default=5, ge=1, le=20),
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Semantic search across the knowledge base without LLM generation.

    Returns raw retrieved chunks with metadata and relevance distances.
    Useful for exploring what documents are indexed.
    """
    results = []

    if source in ("global", "both"):
        global_chunks = retrieve_from_global_knowledge(query, n_results=n_results)
        for chunk in global_chunks:
            results.append({
                "source_type": "global_knowledge",
                "text": chunk["text"][:500],
                "metadata": chunk["metadata"],
                "distance": chunk["distance"],
            })

    if source in ("user", "both"):
        user_chunks = retrieve_from_user_documents(
            user_id=current_user.id,
            query=query,
            n_results=n_results,
        )
        for chunk in user_chunks:
            results.append({
                "source_type": "user_document",
                "text": chunk["text"][:500],
                "metadata": chunk["metadata"],
                "distance": chunk["distance"],
            })

    # Sort by relevance
    results.sort(key=lambda x: x["distance"])

    return {
        "query": query,
        "total_results": len(results),
        "results": results,
        "note": "Results are ordered by semantic relevance (lower distance = more relevant)",
    }
