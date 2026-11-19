
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from pypdf import PdfReader

from healthguard.core.config import settings

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def get_upload_dir() -> Path:
    """Return the configured medical reports directory."""
    return Path(settings.UPLOAD_DIR)


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

    upload_dir = get_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)

    stored_filename = f"{uuid4().hex}.pdf"
    stored_path = upload_dir / stored_filename

    with open(stored_path, "wb") as output:
        output.write(content)

    return {
        "filename": Path(file.filename).name,
        "stored_path": str(stored_path),
        "file_size": len(content),
        "sha256_hash": file_hash,
        "extracted_text": extracted_text
    }


def resolve_stored_document_path(stored_path_str: str) -> Path | None:
    """Resolve a stored medical PDF path safely against configured upload dir, CWD, and repo root."""
    if not stored_path_str:
        return None

    repo_root = Path(__file__).resolve().parents[2]
    allowed_roots = [
        get_upload_dir().resolve(),
        Path("storage/medical_reports").resolve(),
        (repo_root / "storage" / "medical_reports").resolve(),
    ]
    candidates = [
        Path(stored_path_str).resolve(),
        (repo_root / stored_path_str).resolve(),
        (get_upload_dir() / Path(stored_path_str).name).resolve(),
    ]

    for candidate in candidates:
        if any(root in candidate.parents for root in allowed_roots) and candidate.is_file():
            return candidate
    return None


def build_pdf_bytes_from_text(title: str, extracted_text: str) -> bytes:
    """Build a valid single-page PDF 1.4 byte stream from extracted document text."""
    import io

    def _esc(val: str) -> str:
        clean = val.encode("latin-1", errors="replace").decode("latin-1")
        return clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    raw_lines = [f"Document: {title}", "-" * 72] + (extracted_text or "No text available.").splitlines()
    wrapped: list[str] = []
    for line in raw_lines:
        if not line:
            wrapped.append("")
            continue
        while len(line) > 88:
            wrapped.append(line[:88])
            line = line[88:]
        wrapped.append(line)

    lines = wrapped[:48]
    ops = ["BT", "/F1 10 Tf", "45 755 Td", "14 TL"]
    for idx, line in enumerate(lines):
        if idx == 0:
            ops.append(f"({_esc(line)}) Tj")
        else:
            ops.append(f"T* ({_esc(line)}) Tj")
    ops.append("ET")
    stream_bytes = "\n".join(ops).encode("latin-1")

    objects: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        (
            f"5 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
            + stream_bytes
            + b"\nendstream\nendobj\n"
        ),
    ]

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(buf.tell())
        buf.write(obj)

    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    buf.write(b"0000000000 65535 f \n")
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode("latin-1"))

    buf.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("latin-1")
    )
    return buf.getvalue()

