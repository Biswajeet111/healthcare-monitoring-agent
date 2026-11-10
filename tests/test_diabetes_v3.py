import pytest
from unittest.mock import patch

from healthguard.main import app
from healthguard.ml.diabetes_v3_predictor import (
    predict_diabetes_v3,
    validate_features,
    load_v3_model,
    DiabetesInputError,
)


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


def test_v3_model_loads():
    model = load_v3_model()

    assert model is not None
    assert hasattr(model, "predict_proba")


def test_v3_prediction():
    result = predict_diabetes_v3(VALID_INPUT)

    assert result["prediction"] in [0, 1]
    assert 0 <= result["model_score"] <= 1
    assert result["model"] == "LogisticRegression"
    assert result["threshold"] == 0.30


def test_v3_prediction_consistency():
    first = predict_diabetes_v3(VALID_INPUT)
    second = predict_diabetes_v3(VALID_INPUT)

    assert first == second


def test_v3_rejects_missing_feature():
    invalid = VALID_INPUT.copy()
    invalid.pop("Insulin")

    with pytest.raises(ValueError):
        validate_features(invalid)


def test_v3_rejects_extra_feature():
    invalid = VALID_INPUT.copy()
    invalid["Unknown"] = 10

    with pytest.raises(ValueError):
        validate_features(invalid)


def test_v3_rejects_negative_age():
    invalid = VALID_INPUT.copy()
    invalid["Age"] = -5

    with pytest.raises(ValueError):
        validate_features(invalid)


def test_v3_rejects_nan():
    invalid = VALID_INPUT.copy()
    invalid["Glucose"] = float("nan")

    with pytest.raises(ValueError):
        validate_features(invalid)


def test_v3_rejects_infinity():
    invalid = VALID_INPUT.copy()
    invalid["BMI"] = float("inf")

    with pytest.raises(ValueError):
        validate_features(invalid)


def test_v3_rejects_zero_glucose():
    invalid = VALID_INPUT.copy()
    invalid["Glucose"] = 0

    with pytest.raises(ValueError):
        validate_features(invalid)


def test_v3_rejects_boolean():
    invalid = VALID_INPUT.copy()
    invalid["Age"] = True

    with pytest.raises(ValueError):
        validate_features(invalid)


def test_v3_has_medical_disclaimer():
    result = predict_diabetes_v3(VALID_INPUT)

    disclaimer = result["disclaimer"].lower()

    assert "not a medical diagnosis" in disclaimer
    assert "not been clinically validated" in disclaimer

def v3_auth_headers(client):
    registration = client.post(
        "/auth/register",
        json={
            "full_name": "V3 Test User",
            "email": "v3test@example.com",
            "password": "TestPassword@123",
        },
    )

    assert registration.status_code in (200, 201)

    login = client.post(
        "/auth/login",
        json={
            "email": "v3test@example.com",
            "password": "TestPassword@123",
        },
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    return {
        "Authorization": f"Bearer {token}"
    }


def test_v3_api_requires_authentication(client):
    response = client.post(
        "/ml/diabetes/predict-v3",
        json=VALID_INPUT,
    )

    assert response.status_code == 401


def test_v3_api_authenticated_prediction(client):
    headers = v3_auth_headers(client)

    response = client.post(
        "/ml/diabetes/predict-v3",
        json=VALID_INPUT,
        headers=headers,
    )

    assert response.status_code == 200, response.text

    result = response.json()

    assert result["prediction"] in [0, 1]
    assert result["model"] == "LogisticRegression"
    assert result["model_version"] == "experimental-v3-candidate"
    assert result["threshold"] == 0.30
    assert 0 <= result["model_score"] <= 1
    assert "disclaimer" in result


def test_v3_api_rejects_missing_feature(client):
    headers = v3_auth_headers(client)

    invalid = VALID_INPUT.copy()
    invalid.pop("Insulin")

    response = client.post(
        "/ml/diabetes/predict-v3",
        json=invalid,
        headers=headers,
    )

    assert response.status_code == 422


def test_v3_api_rejects_zero_glucose(client):
    headers = v3_auth_headers(client)

    invalid = VALID_INPUT.copy()
    invalid["Glucose"] = 0

    response = client.post(
        "/ml/diabetes/predict-v3",
        json=invalid,
        headers=headers,
    )

    assert response.status_code == 422


def test_v3_api_rejects_invalid_jwt(client):
    response = client.post(
        "/ml/diabetes/predict-v3",
        json=VALID_INPUT,
        headers={
            "Authorization": "Bearer invalid-token"
        },
    )

    assert response.status_code == 401


def test_v3_api_handles_missing_model(client):
    headers = v3_auth_headers(client)

    with patch(
        "healthguard.main.predict_diabetes_v3",
        side_effect=FileNotFoundError("Model unavailable"),
    ):
        response = client.post(
            "/ml/diabetes/predict-v3",
            json=VALID_INPUT,
            headers=headers,
        )

    assert response.status_code == 503


def test_v3_api_handles_invalid_model_metadata(client):
    headers = v3_auth_headers(client)

    with patch(
        "healthguard.main.predict_diabetes_v3",
        side_effect=ValueError("Model threshold mismatch"),
    ):
        response = client.post(
            "/ml/diabetes/predict-v3",
            json=VALID_INPUT,
            headers=headers,
        )

    assert response.status_code == 503

def test_v3_rejects_age_outside_range():
    invalid = VALID_INPUT.copy()
    invalid["Age"] = 500

    with pytest.raises(DiabetesInputError):
        validate_features(invalid)


def test_v3_rejects_glucose_outside_range():
    invalid = VALID_INPUT.copy()
    invalid["Glucose"] = 700

    with pytest.raises(DiabetesInputError):
        validate_features(invalid)