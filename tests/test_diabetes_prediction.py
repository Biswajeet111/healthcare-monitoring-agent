import pytest
from fastapi.testclient import TestClient

from healthguard.main import app
from healthguard.ml.diabetes_predictor import predict_diabetes
from unittest.mock import patch


VALID_INPUT = {
    "Pregnancies": 2,
    "Glucose": 140,
    "BloodPressure": 80,
    "SkinThickness": 25,
    "Insulin": 100,
    "BMI": 30.5,
    "DiabetesPedigreeFunction": 0.5,
    "Age": 45,
}


def test_model_prediction():
    result = predict_diabetes(VALID_INPUT)

    assert result["prediction"] in [0, 1]
    assert 0 <= result["model_score"] <= 1
    assert result["model"] == "XGBoost"


def test_prediction_consistency():
    first = predict_diabetes(VALID_INPUT)
    second = predict_diabetes(VALID_INPUT)

    assert first == second


def test_model_rejects_nan():
    invalid = VALID_INPUT.copy()
    invalid["Glucose"] = float("nan")

    with pytest.raises(ValueError):
        predict_diabetes(invalid)


def test_model_rejects_infinity():
    invalid = VALID_INPUT.copy()
    invalid["BMI"] = float("inf")

    with pytest.raises(ValueError):
        predict_diabetes(invalid)


def test_schema_rejects_missing_feature():
    from healthguard.schemas import DiabetesPredictionRequest

    invalid = VALID_INPUT.copy()
    invalid.pop("Insulin")

    with pytest.raises(ValueError):
        DiabetesPredictionRequest(**invalid)


def test_schema_rejects_negative_age():
    from healthguard.schemas import DiabetesPredictionRequest

    invalid = VALID_INPUT.copy()
    invalid["Age"] = -5

    with pytest.raises(ValueError):
        DiabetesPredictionRequest(**invalid)


def test_schema_rejects_extra_feature():
    from healthguard.schemas import DiabetesPredictionRequest

    invalid = VALID_INPUT.copy()
    invalid["UnknownFeature"] = 10

    with pytest.raises(ValueError):
        DiabetesPredictionRequest(**invalid)


def get_auth_headers(client):
    """Register a temporary test user and obtain a JWT."""

    response = client.post(
        "/auth/register",
        json={
            "full_name": "ML Test User",
            "email": "mltest@example.com",
            "password": "TestPassword@123",
        },
    )

    assert response.status_code == 200, response.text

    response = client.post(
        "/auth/login",
        json={
            "email": "mltest@example.com",
            "password": "TestPassword@123",
        },
    )

    assert response.status_code == 200, response.text

    token = response.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


def test_prediction_requires_authentication(client):
    response = client.post(
        "/ml/diabetes/predict",
        json=VALID_INPUT,
    )

    assert response.status_code == 401


def test_authenticated_prediction(client):
    headers = get_auth_headers(client)

    response = client.post(
        "/ml/diabetes/predict",
        json=VALID_INPUT,
        headers=headers,
    )

    assert response.status_code == 200, response.text

    result = response.json()

    assert result["prediction"] in [0, 1]
    assert 0 <= result["model_score"] <= 1
    assert result["model"] == "XGBoost"
    assert result["model_version"] == "experimental-v1"
    assert "disclaimer" in result


def test_api_rejects_missing_feature(client):
    headers = get_auth_headers(client)

    invalid = VALID_INPUT.copy()
    invalid.pop("Insulin")

    response = client.post(
        "/ml/diabetes/predict",
        json=invalid,
        headers=headers,
    )

    assert response.status_code == 422


def test_api_rejects_negative_age(client):
    headers = get_auth_headers(client)

    invalid = VALID_INPUT.copy()
    invalid["Age"] = -5

    response = client.post(
        "/ml/diabetes/predict",
        json=invalid,
        headers=headers,
    )

    assert response.status_code == 422


def test_api_rejects_extra_feature(client):
    headers = get_auth_headers(client)

    invalid = VALID_INPUT.copy()
    invalid["UnknownFeature"] = 10

    response = client.post(
        "/ml/diabetes/predict",
        json=invalid,
        headers=headers,
    )

    assert response.status_code == 422


def test_api_rejects_invalid_jwt(client):
    response = client.post(
        "/ml/diabetes/predict",
        json=VALID_INPUT,
        headers={
            "Authorization": "Bearer invalid-token"
        },
    )

    assert response.status_code == 401


def test_api_handles_missing_model(client):
    headers = get_auth_headers(client)

    with patch(
        "healthguard.main.predict_diabetes",
        side_effect=FileNotFoundError("Model unavailable"),
    ):
        response = client.post(
            "/ml/diabetes/predict",
            json=VALID_INPUT,
            headers=headers,
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Diabetes screening service is unavailable"
    )