"""
Repair HealthGuard AI's missing global ChromaDB index.

Reads existing approved medical knowledge chunks from SQLite.
Recreates their embeddings using all-MiniLM-L6-v2.
Does not delete existing collections or modify SQL records.
"""

from collections import Counter

from healthguard.database.session import SessionLocal
from healthguard.database.models import (
    MedicalKnowledgeDocument,
    MedicalKnowledgeChunk,
)
from healthguard.rag.embedding_service import get_embedding_model
from healthguard.rag.vector_store import get_global_collection


BATCH_SIZE = 64


def main():
    model = get_embedding_model()

    if model is None:
        raise RuntimeError(
            "SentenceTransformer unavailable. "
            "Refusing to rebuild using HashingVectorizer."
        )

    collection = get_global_collection()

    print("Embedding model:", type(model).__name__)
    print("Collection:", collection.name)
    print("Existing vectors:", collection.count())

    db = SessionLocal()

    try:
        documents = {
            doc.id: doc
            for doc in db.query(MedicalKnowledgeDocument).all()
        }

        chunks = (
            db.query(MedicalKnowledgeChunk)
            .order_by(
                MedicalKnowledgeChunk.document_id,
                MedicalKnowledgeChunk.chunk_index,
            )
            .all()
        )

        print("SQLite chunks:", len(chunks))

        if not chunks:
            raise RuntimeError("No medical knowledge chunks found.")

        missing_documents = {
            chunk.document_id
            for chunk in chunks
            if chunk.document_id not in documents
        }

        if missing_documents:
            raise RuntimeError(
                f"Missing document records: {missing_documents}"
            )

        completed = 0

        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start:start + BATCH_SIZE]

            ids = [chunk.chroma_id for chunk in batch]
            texts = [chunk.text for chunk in batch]

            embeddings = model.encode(
                texts,
                show_progress_bar=False,
            ).tolist()

            metadatas = []

            for chunk in batch:
                doc = documents[chunk.document_id]

                metadatas.append({
                    "document_id": str(doc.id),
                    "title": doc.title or "",
                    "source_organization": doc.source_organization or "",
                    "source_url": doc.source_url or "",
                    "document_type": doc.document_type or "",
                    "publication_date": doc.publication_date or "",
                    "chunk_index": str(chunk.chunk_index),
                })

            collection.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )

            completed += len(batch)

            print(
                f"Indexed {completed}/{len(chunks)} chunks",
                flush=True,
            )

        print("\nREPAIR COMPLETE")
        print("SQLite chunks:", len(chunks))
        print("ChromaDB vectors:", collection.count())

        if collection.count() != len(chunks):
            print(
                "WARNING: Vector count differs from SQLite count. "
                "Investigate before considering repair complete."
            )

    finally:
        db.close()


if __name__ == "__main__":
    main()