"""
Script to ingest approved medical reference documents into global knowledge base.
"""
from pathlib import Path
from healthguard.database.session import SessionLocal
from healthguard.rag.document_ingestion import ingest_global_document


def main():
    db = SessionLocal()
    doc_folder = Path("Document")

    docs_to_ingest = [
        {
            "path": doc_folder / "AHA-GUIDELINEDRIVEN-MANAGEMENT-OF-HYPERTENSION--AN-EVIDENCEBASED-UPDATE.pdf",
            "title": "AHA Guideline-Driven Management of Hypertension: An Evidence-Based Update",
            "org": "American Heart Association (AHA)",
            "type": "Clinical Guideline",
        },
        {
            "path": doc_folder / "guidance-on-global-monitoring-for-diabetes.pdf",
            "title": "Guidance on Global Monitoring for Diabetes",
            "org": "World Health Organization (WHO)",
            "type": "Global Guidance",
        },
        {
            "path": doc_folder / "cardiovascular.pdf",
            "title": "Cardiovascular Disease Management and Risk Reduction",
            "org": "Clinical Reference",
            "type": "Reference Guideline",
        },
        {
            "path": doc_folder / "diagnoisis.pdf",
            "title": "Diagnosis and Classification of Diabetes",
            "org": "Clinical Reference",
            "type": "Diagnostic Standard",
        },
        {
            "path": doc_folder / "pharmacologic.pdf",
            "title": "Pharmacologic Approaches to Glycemic Treatment",
            "org": "Clinical Reference",
            "type": "Pharmacologic Guideline",
        },
        {
            "path": doc_folder / "prevention.pdf",
            "title": "Prevention or Delay of Diabetes and Associated Comorbidities",
            "org": "Clinical Reference",
            "type": "Prevention Standard",
        },
        {
            "path": doc_folder / "who file.pdf",
            "title": "WHO Guidelines on Noncommunicable Diseases and Health Monitoring",
            "org": "World Health Organization (WHO)",
            "type": "Public Health Guideline",
        },
    ]

    for item in docs_to_ingest:
        path = item["path"]
        title = item["title"]
        if path.exists():
            print(f"Ingesting: {title} ({path.name})...")
            res = ingest_global_document(
                db=db,
                file_path=str(path),
                title=title,
                source_organization=item["org"],
                document_type=item["type"],
            )
            db.commit()
            print(f"Status: {res.get('status')}, Chunks: {res.get('chunks_created')}")
        else:
            print(f"Not found: {path}")

    db.close()
    print("Ingestion complete.")


if __name__ == "__main__":
    main()
