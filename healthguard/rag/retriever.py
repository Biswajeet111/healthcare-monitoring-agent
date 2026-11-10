"""
RAG Retriever — Phase 7

Retrieves relevant text chunks from ChromaDB based on semantic similarity.

Access control:
- Global knowledge: accessible to all authenticated users.
- User documents: only the owning user can retrieve from their collection.
- Access is enforced at the retrieval layer, not just prompts.

Similarity filtering:
- Chunks with distance > MAX_DISTANCE are considered irrelevant and excluded.
- ChromaDB cosine distance: 0 = identical, 2 = opposite.
  Practical relevance threshold: < 1.0
"""

import logging
from typing import Optional

from healthguard.rag.embedding_service import embed_query
from healthguard.rag.vector_store import query_global, query_user_documents

logger = logging.getLogger(__name__)

MAX_DISTANCE = 1.2  # Chunks further than this are discarded as irrelevant


def _parse_chroma_results(result: dict) -> list[dict]:
    """
    Convert ChromaDB query results to a list of chunk dicts.

    Each chunk dict contains: text, metadata, distance.
    """
    chunks = []
    ids_list = result.get("ids", [[]])[0]
    docs_list = result.get("documents", [[]])[0]
    metas_list = result.get("metadatas", [[]])[0]
    dists_list = result.get("distances", [[]])[0]

    for chunk_id, doc_text, meta, dist in zip(ids_list, docs_list, metas_list, dists_list):
        chunks.append({
            "id": chunk_id,
            "text": doc_text,
            "metadata": meta,
            "distance": dist,
        })
    return chunks


def _filter_by_relevance(chunks: list[dict], max_distance: float = MAX_DISTANCE) -> list[dict]:
    """Remove chunks with distance exceeding the threshold."""
    return [c for c in chunks if c["distance"] <= max_distance]


def _deduplicate_chunks(chunks: list[dict]) -> list[dict]:
    """Remove duplicate chunk texts (same content, different embeddings are possible)."""
    seen_texts = set()
    unique = []
    for chunk in chunks:
        text_key = chunk["text"][:200]  # compare first 200 chars as fingerprint
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            unique.append(chunk)
    return unique


def retrieve_from_global_knowledge(
    query: str,
    n_results: int = 5,
) -> list[dict]:
    """
    Retrieve relevant chunks from the global medical knowledge base.

    Returns list of chunk dicts with text, metadata (source, title, etc.), and distance.
    Returns empty list if the knowledge base is empty or query fails.
    """
    if not query.strip():
        return []

    try:
        query_embedding = embed_query(query)
    except RuntimeError as exc:
        logger.error("Embedding failed for global retrieval: %s", exc)
        return []

    result = query_global(query_embedding, n_results=n_results)
    chunks = _parse_chroma_results(result)
    chunks = _filter_by_relevance(chunks)
    chunks = _deduplicate_chunks(chunks)
    chunks.sort(key=lambda c: c["distance"])  # most relevant first

    logger.debug(
        "Global knowledge retrieval: query='%s...', returned %d relevant chunks",
        query[:50],
        len(chunks),
    )
    return chunks


def retrieve_from_user_documents(
    user_id: int,
    query: str,
    n_results: int = 5,
    document_id: Optional[int] = None,
) -> list[dict]:
    """
    Retrieve relevant chunks from a user's private document collection.

    Enforces user ownership at the collection level.
    Returns empty list if the user has no indexed documents or query fails.
    """
    if not query.strip():
        return []

    try:
        query_embedding = embed_query(query)
    except RuntimeError as exc:
        logger.error("Embedding failed for user %s document retrieval: %s", user_id, exc)
        return []

    result = query_user_documents(
        user_id=user_id,
        query_embedding=query_embedding,
        n_results=n_results,
        document_id=document_id,
    )
    chunks = _parse_chroma_results(result)
    chunks = _filter_by_relevance(chunks)
    chunks = _deduplicate_chunks(chunks)
    chunks.sort(key=lambda c: c["distance"])

    logger.debug(
        "User %s document retrieval: returned %d relevant chunks",
        user_id,
        len(chunks),
    )
    return chunks


def classify_query_intent(query: str) -> dict:
    """
    Determine what sources a query likely needs.

    Returns a dict with boolean flags for routing purposes.
    Uses simple keyword heuristics — no LLM required for routing.
    """
    q_lower = query.lower()

    needs_general_knowledge = any(word in q_lower for word in [
        "what is", "what are", "how does", "explain", "define",
        "symptoms", "causes", "treatment", "medication", "drug",
        "condition", "disease", "diabetes", "hypertension", "cholesterol",
        "hba1c", "blood pressure", "glucose", "heart", "cardiovascular",
    ])

    needs_personal_history = any(word in q_lower for word in [
        "my blood", "my glucose", "my pressure", "my readings",
        "my history", "my measurements", "my health", "last month",
        "last week", "past 30", "past week", "trend", "change",
        "how has my", "show my",
    ])

    needs_medication_info = any(word in q_lower for word in [
        "my medication", "my medicine", "my prescription", "adherence",
        "did i take", "my dose", "my pill", "my drugs",
    ])

    needs_user_documents = any(word in q_lower for word in [
        "my report", "my document", "my test", "my lab", "my scan",
        "uploaded", "my file", "my record", "summarize my",
    ])

    return {
        "needs_general_knowledge": needs_general_knowledge,
        "needs_personal_history": needs_personal_history,
        "needs_medication_info": needs_medication_info,
        "needs_user_documents": needs_user_documents,
    }
