
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader

UPLOAD_DIR = Path("storage/medical_reports")
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


async def process_medical_pdf(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty")

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="PDF exceeds 10 MB limit")

    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid PDF file")

    try:
        import io
        reader = PdfReader(io.BytesIO(content), strict=True)

        if reader.is_encrypted:
            raise HTTPException(
                status_code=400,
                detail="Encrypted PDFs are not supported"
            )

        extracted_text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()

        if not extracted_text:
            raise HTTPException(
                status_code=422,
                detail="No extractable text found. Scanned PDFs require OCR."
            )

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read PDF file")

    file_hash = hashlib.sha256(content).hexdigest()

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    stored_filename = f"{uuid4().hex}.pdf"
    stored_path = UPLOAD_DIR / stored_filename

    with open(stored_path, "wb") as output:
        output.write(content)

    return {
        "filename": Path(file.filename).name,
        "stored_path": str(stored_path),
        "file_size": len(content),
        "sha256_hash": file_hash,
        "extracted_text": extracted_text
    }
