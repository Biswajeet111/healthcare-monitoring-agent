"""
Document Ingestion Pipeline — Phase 7

Ingests approved medical documents into ChromaDB for RAG retrieval.

Supported:
- PDF files (text-extractable)
- Plain text files (.txt)
- Markdown files (.md)

Limitations (documented, not hidden):
- Scanned / image-only PDFs: extraction will fail and status set to 'not_applicable'
- OCR is not implemented

Duplicate detection: SHA-256 of raw file content.
Metadata enrichment: title, source, URL, dates from caller-supplied metadata.
"""

import hashlib
import io
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from healthguard.database.models import (
    MedicalKnowledgeChunk,
    MedicalKnowledgeDocument,
    MedicalDocument,
    DocumentIndexStatus,
)
from healthguard.rag.embedding_service import embed_texts
from healthguard.rag.vector_store import (
    add_chunks_to_global,
    add_chunks_to_user,
    delete_chunks_from_user,
    delete_chunks_from_global,
)

logger = logging.getLogger(__name__)

# Chunk settings
CHUNK_SIZE = 500          # characters per chunk
CHUNK_OVERLAP = 100       # overlap between consecutive chunks
MIN_CHUNK_LENGTH = 50     # discard chunks shorter than this


def _hash_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _extract_text_from_pdf(content: bytes) -> Optional[str]:
    """Extract text from a PDF. Returns None if extraction fails."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            logger.warning("PDF is encrypted; cannot extract text.")
            return None
        pages = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            pages.append(page_text)
        text = "\n".join(pages).strip()
        return text if text else None
    except Exception as exc:
        logger.error("PDF text extraction failed: %s", exc)
        return None


def _extract_text_from_txt(content: bytes) -> Optional[str]:
    """Extract text from UTF-8 or latin-1 text file."""
    for encoding in ("utf-8", "latin-1"):
        try:
            return content.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return None


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by character count."""
    if not text:
        return []

    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if len(chunk) >= MIN_CHUNK_LENGTH:
            chunks.append(chunk)
        start += chunk_size - overlap

    return chunks


def ingest_global_document(
    db: Session,
    file_path: str,
    title: str,
    source_organization: Optional[str] = None,
    source_url: Optional[str] = None,
    document_type: Optional[str] = None,
    publication_date: Optional[str] = None,
    review_date: Optional[str] = None,
) -> dict:
    """
    Ingest an approved medical document into the global knowledge base.

    Returns a summary dict with status and counts.
    Does NOT fabricate metadata — only stores what is explicitly provided.
    """
    path = Path(file_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    content = path.read_bytes()
    content_hash = _hash_content(content)

    # Duplicate detection
    existing = (
        db.query(MedicalKnowledgeDocument)
        .filter(MedicalKnowledgeDocument.content_hash == content_hash)
        .first()
    )
    if existing:
        return {
            "status": "duplicate",
            "document_id": existing.id,
            "message": f"Document already ingested (ID={existing.id})",
        }

    # Text extraction
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _extract_text_from_pdf(content)
    elif suffix in (".txt", ".md"):
        text = _extract_text_from_txt(content)
    else:
        return {"status": "error", "message": f"Unsupported file type: {suffix}"}

    if not text:
        return {
            "status": "failed",
            "message": "No extractable text. Scanned PDFs require OCR (not implemented).",
        }

    # Create knowledge document record
    doc = MedicalKnowledgeDocument(
        title=title,
        source_organization=source_organization,
        source_url=source_url,
        document_type=document_type,
        publication_date=publication_date,
        review_date=review_date,
        content_hash=content_hash,
        source_path=str(path),
        index_status="pending",
        ingested_at=datetime.utcnow(),
    )
    db.add(doc)
    db.flush()  # get doc.id

    # Chunk the text
    chunks = _chunk_text(text)
    if not chunks:
        doc.index_status = "failed"
        db.flush()
        return {"status": "failed", "message": "Text chunking produced no usable chunks"}

    # Embed chunks
    try:
        embeddings = embed_texts(chunks)
    except RuntimeError as exc:
        doc.index_status = "failed"
        db.flush()
        return {"status": "failed", "message": f"Embedding failed: {exc}"}

    # Persist chunks and add to ChromaDB
    chroma_ids = []
    chroma_texts = []
    chroma_embeddings = []
    chroma_metadatas = []
    db_chunks = []

    for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
        chroma_id = f"knowledge-doc-{doc.id}-chunk-{idx}"
        db_chunk = MedicalKnowledgeChunk(
            document_id=doc.id,
            chroma_id=chroma_id,
            chunk_index=idx,
            text=chunk_text,
            created_at=datetime.utcnow(),
        )
        db.add(db_chunk)
        db_chunks.append(db_chunk)

        chroma_ids.append(chroma_id)
        chroma_texts.append(chunk_text)
        chroma_embeddings.append(embedding)
        chroma_metadatas.append({
            "document_id": str(doc.id),
            "title": title,
            "source_organization": source_organization or "",
            "source_url": source_url or "",
            "document_type": document_type or "",
            "publication_date": publication_date or "",
            "chunk_index": str(idx),
        })

    try:
        add_chunks_to_global(chroma_ids, chroma_texts, chroma_embeddings, chroma_metadatas)
    except Exception as exc:
        doc.index_status = "failed"
        db.flush()
        return {"status": "failed", "message": f"ChromaDB insertion failed: {exc}"}

    doc.index_status = "indexed"
    doc.indexed_at = datetime.utcnow()
    db.flush()

    return {
        "status": "indexed",
        "document_id": doc.id,
        "title": title,
        "chunks_created": len(chunks),
        "content_hash": content_hash,
    }


def ingest_user_document(
    db: Session,
    medical_document_id: int,
    user_id: int,
) -> dict:
    """
    Index a user-uploaded MedicalDocument into their private ChromaDB collection.

    Uses the extracted_text already stored in the MedicalDocument record.
    Sets the DocumentIndexStatus record accordingly.
    """
    from healthguard.database.models import MedicalDocument

    document = (
        db.query(MedicalDocument)
        .filter(
            MedicalDocument.id == medical_document_id,
            MedicalDocument.user_id == user_id,
        )
        .first()
    )

    if not document:
        return {"status": "error", "message": "Document not found or access denied"}

    # Get or create index status record
    index_status = (
        db.query(DocumentIndexStatus)
        .filter(DocumentIndexStatus.document_id == medical_document_id)
        .first()
    )
    if not index_status:
        index_status = DocumentIndexStatus(
            document_id=medical_document_id,
            user_id=user_id,
            status="pending",
            created_at=datetime.utcnow(),
        )
        db.add(index_status)
        db.flush()

    if not document.extracted_text:
        index_status.status = "not_applicable"
        index_status.error_message = "No extractable text. Scanned PDF or empty document."
        db.flush()
        return {
            "status": "not_applicable",
            "message": "No extractable text available for indexing.",
        }

    text = document.extracted_text.strip()
    chunks = _chunk_text(text)

    if not chunks:
        index_status.status = "not_applicable"
        index_status.error_message = "Text too short to chunk."
        db.flush()
        return {"status": "not_applicable", "message": "Document text too short to index."}

    # Embed
    try:
        embeddings = embed_texts(chunks)
    except RuntimeError as exc:
        index_status.status = "failed"
        index_status.error_message = str(exc)
        db.flush()
        return {"status": "failed", "message": f"Embedding failed: {exc}"}

    chroma_ids = []
    chroma_texts = []
    chroma_embeddings = []
    chroma_metadatas = []

    for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
        chroma_id = f"user-{user_id}-doc-{medical_document_id}-chunk-{idx}"
        chroma_ids.append(chroma_id)
        chroma_texts.append(chunk_text)
        chroma_embeddings.append(embedding)
        chroma_metadatas.append({
            "document_id": str(medical_document_id),
            "user_id": str(user_id),
            "filename": document.filename,
            "chunk_index": str(idx),
        })

    try:
        add_chunks_to_user(user_id, chroma_ids, chroma_texts, chroma_embeddings, chroma_metadatas)
    except Exception as exc:
        index_status.status = "failed"
        index_status.error_message = f"ChromaDB insertion failed: {exc}"
        db.flush()
        return {"status": "failed", "message": f"ChromaDB insertion failed: {exc}"}

    index_status.status = "indexed"
    index_status.chunk_count = len(chunks)
    index_status.indexed_at = datetime.utcnow()
    index_status.error_message = None
    db.flush()

    return {
        "status": "indexed",
        "document_id": medical_document_id,
        "chunks_created": len(chunks),
    }


def delete_user_document_index(
    db: Session,
    medical_document_id: int,
    user_id: int,
) -> None:
    """
    Remove all ChromaDB chunks for a user document when it is deleted.
    Enforces user ownership before deletion.
    """
    index_status = (
        db.query(DocumentIndexStatus)
        .filter(
            DocumentIndexStatus.document_id == medical_document_id,
            DocumentIndexStatus.user_id == user_id,
        )
        .first()
    )

    if not index_status or index_status.status != "indexed":
        return

    # Reconstruct chunk IDs (same pattern used during indexing)
    chunk_count = index_status.chunk_count or 0
    if chunk_count > 0:
        chunk_ids = [
            f"user-{user_id}-doc-{medical_document_id}-chunk-{i}"
            for i in range(chunk_count)
        ]
        delete_chunks_from_user(user_id, chunk_ids)

    db.delete(index_status)
    db.flush()
    logger.info(
        "Deleted index for user %s document %s (%d chunks).",
        user_id,
        medical_document_id,
        chunk_count,
    )
