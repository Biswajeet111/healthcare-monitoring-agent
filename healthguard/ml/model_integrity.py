"""Integrity verification for trusted local ML artifacts."""

import hashlib
import os
from pathlib import Path


class ModelIntegrityError(RuntimeError):
    """Raised when model artifact integrity verification fails."""


def calculate_sha256(file_path: Path) -> str:
    """Calculate a file's SHA-256 digest without loading it into memory."""

    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def verify_model_integrity(model_path: Path) -> bool:
    """Verify model checksum against trusted deployment configuration."""

    expected = os.getenv("DIABETES_V3_SHA256")

    if not expected:
        raise ModelIntegrityError(
            "DIABETES_V3_SHA256 is not configured"
        )

    expected = expected.strip().lower()

    if len(expected) != 64 or any(
        character not in "0123456789abcdef"
        for character in expected
    ):
        raise ModelIntegrityError(
            "Invalid expected SHA-256 checksum"
        )

    if not model_path.is_file():
        raise ModelIntegrityError(
            "Model artifact is unavailable"
        )

    actual = calculate_sha256(model_path)

    if actual != expected:
        raise ModelIntegrityError(
            "Model artifact checksum mismatch"
        )

    return True