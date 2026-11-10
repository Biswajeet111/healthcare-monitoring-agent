import hashlib

import pytest

from healthguard.ml.model_integrity import (
    ModelIntegrityError,
    verify_model_integrity,
)
from dotenv import load_dotenv

load_dotenv()

def test_integrity_valid_checksum(tmp_path, monkeypatch):
    model = tmp_path / "model.joblib"
    model.write_bytes(b"trusted-model")

    checksum = hashlib.sha256(b"trusted-model").hexdigest()

    monkeypatch.setenv("DIABETES_V3_SHA256", checksum)

    assert verify_model_integrity(model) is True


def test_integrity_modified_model(tmp_path, monkeypatch):
    model = tmp_path / "model.joblib"
    model.write_bytes(b"original-model")

    checksum = hashlib.sha256(b"original-model").hexdigest()

    monkeypatch.setenv("DIABETES_V3_SHA256", checksum)

    model.write_bytes(b"modified-model")

    with pytest.raises(ModelIntegrityError):
        verify_model_integrity(model)


def test_integrity_missing_checksum(tmp_path, monkeypatch):
    model = tmp_path / "model.joblib"
    model.write_bytes(b"trusted-model")

    monkeypatch.delenv("DIABETES_V3_SHA256", raising=False)

    with pytest.raises(ModelIntegrityError):
        verify_model_integrity(model)


def test_integrity_invalid_checksum(tmp_path, monkeypatch):
    model = tmp_path / "model.joblib"
    model.write_bytes(b"trusted-model")

    monkeypatch.setenv("DIABETES_V3_SHA256", "invalid")

    with pytest.raises(ModelIntegrityError):
        verify_model_integrity(model)


def test_integrity_missing_artifact(tmp_path, monkeypatch):
    missing_model = tmp_path / "missing.joblib"

    monkeypatch.setenv(
        "DIABETES_V3_SHA256",
        "a" * 64,
    )

    with pytest.raises(ModelIntegrityError):
        verify_model_integrity(missing_model)