"""
Embedding Service — Phase 7

Provides local embeddings:
1. Attempts to use SentenceTransformer (all-MiniLM-L6-v2).
2. If the neural model cannot be reached or downloaded (e.g. offline sandbox),
   falls back seamlessly to a deterministic, L2-normalized 384-dimensional
   HashingVectorizer so vector storage and retrieval always function locally
   without external network access.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_ST_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_st_model = None
_st_load_attempted = False
_hashing_vectorizer = None


def _get_hashing_vectorizer():
    global _hashing_vectorizer
    if _hashing_vectorizer is None:
        from sklearn.feature_extraction.text import HashingVectorizer
        _hashing_vectorizer = HashingVectorizer(
            n_features=EMBEDDING_DIM,
            norm="l2",
            alternate_sign=False,
        )
    return _hashing_vectorizer


def _fallback_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic local embedding using HashingVectorizer with L2 normalization."""
    hv = _get_hashing_vectorizer()
    matrix = hv.transform(texts).toarray()
    return matrix.tolist()


def get_embedding_model(model_name: Optional[str] = None):
    """Attempt to load SentenceTransformer model if available locally without blocking."""
    global _st_model, _st_load_attempted
    if _st_model is not None:
        return _st_model
    if _st_load_attempted:
        return None

    _st_load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        name = model_name or DEFAULT_ST_MODEL
        model = SentenceTransformer(name, local_files_only=True)
        _st_model = model
        logger.info("SentenceTransformer model loaded locally: %s", name)
        return _st_model
    except Exception as exc:
        logger.info(
            "SentenceTransformer not cached locally (%s). Using deterministic local vectorizer fallback.",
            exc,
        )
        return None


def embed_texts(texts: list[str], model_name: Optional[str] = None) -> list[list[float]]:
    """
    Embed a list of text strings.
    Always succeeds: uses local SentenceTransformer if cached, else deterministic local vectorizer.
    """
    if not texts:
        return []

    model = get_embedding_model(model_name)
    if model is not None:
        try:
            embeddings = model.encode(texts, show_progress_bar=False)
            return [emb.tolist() for emb in embeddings]
        except Exception as exc:
            logger.warning("Neural embedding failed (%s), using local fallback.", exc)

    return _fallback_embed(texts)


def embed_query(query: str, model_name: Optional[str] = None) -> list[float]:
    """Embed a single query string into a 384-dimensional vector."""
    results = embed_texts([query], model_name)
    if not results:
        return [0.0] * EMBEDDING_DIM
    return results[0]
