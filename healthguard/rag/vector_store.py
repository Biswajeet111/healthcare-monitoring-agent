"""
Vector Store — Phase 7

Manages two ChromaDB collections:
1. "medical_knowledge" — global approved medical documents (WHO, MedlinePlus, etc.)
2. "user_documents_{user_id}" — private user-uploaded documents (per-user isolation)

Access control is enforced at the storage layer, not just prompts.
Users can never retrieve another user's private documents.
"""

import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)

# ChromaDB persisted at data/vector_db
VECTOR_DB_PATH = str(Path(__file__).resolve().parents[2] / "data" / "vector_db")

GLOBAL_KNOWLEDGE_COLLECTION = "medical_knowledge"
USER_DOC_COLLECTION_PREFIX = "user_documents_"


def _get_chroma_client() -> chromadb.ClientAPI:
    """Return a persistent ChromaDB client."""
    return chromadb.PersistentClient(
        path=VECTOR_DB_PATH,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_global_collection() -> chromadb.Collection:
    """Return (or create) the global medical knowledge collection."""
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=GLOBAL_KNOWLEDGE_COLLECTION,
        metadata={"description": "Approved global medical knowledge documents"},
    )


def get_user_collection(user_id: int) -> chromadb.Collection:
    """
    Return (or create) the per-user private document collection.

    Collection name encodes the user_id to enforce isolation.
    """
    client = _get_chroma_client()
    collection_name = f"{USER_DOC_COLLECTION_PREFIX}{user_id}"
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"user_id": str(user_id), "description": "Private user medical documents"},
    )


def add_chunks_to_global(
    chunk_ids: list[str],
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    """Add chunks to the global knowledge collection."""
    collection = get_global_collection()
    collection.add(
        ids=chunk_ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    logger.info("Added %d chunks to global knowledge collection.", len(chunk_ids))


def add_chunks_to_user(
    user_id: int,
    chunk_ids: list[str],
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    """Add chunks to a user's private collection."""
    collection = get_user_collection(user_id)
    collection.add(
        ids=chunk_ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    logger.info(
        "Added %d chunks to user %s private collection.", len(chunk_ids), user_id
    )


def query_global(
    query_embedding: list[float],
    n_results: int = 5,
    where: Optional[dict] = None,
) -> dict:
    """
    Retrieve top-k chunks from the global knowledge collection.
    Returns ChromaDB query result dict.
    """
    collection = get_global_collection()
    kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where
    try:
        return collection.query(**kwargs)
    except Exception as exc:
        logger.error("Global knowledge query failed: %s", exc)
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def query_user_documents(
    user_id: int,
    query_embedding: list[float],
    n_results: int = 5,
    document_id: Optional[int] = None,
) -> dict:
    """
    Retrieve top-k chunks from a user's private collection.

    Optionally filter by specific document_id.
    Enforces that only user_id's collection is queried.
    """
    collection = get_user_collection(user_id)

    where: Optional[dict] = None
    if document_id is not None:
        where = {"document_id": str(document_id)}

    kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    try:
        return collection.query(**kwargs)
    except Exception as exc:
        logger.error("User %s document query failed: %s", user_id, exc)
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def delete_chunks_from_user(user_id: int, chunk_ids: list[str]) -> None:
    """Remove specific chunks from a user's collection."""
    if not chunk_ids:
        return
    try:
        collection = get_user_collection(user_id)
        collection.delete(ids=chunk_ids)
        logger.info(
            "Deleted %d chunks from user %s collection.", len(chunk_ids), user_id
        )
    except Exception as exc:
        logger.error(
            "Failed to delete chunks from user %s collection: %s", user_id, exc
        )


def delete_chunks_from_global(chunk_ids: list[str]) -> None:
    """Remove specific chunks from the global knowledge collection."""
    if not chunk_ids:
        return
    try:
        collection = get_global_collection()
        collection.delete(ids=chunk_ids)
        logger.info("Deleted %d chunks from global knowledge collection.", len(chunk_ids))
    except Exception as exc:
        logger.error("Failed to delete chunks from global collection: %s", exc)


def collection_count(collection_name: str) -> int:
    """Return the number of chunks in a collection. Returns 0 if error."""
    try:
        client = _get_chroma_client()
        col = client.get_collection(collection_name)
        return col.count()
    except Exception:
        return 0
