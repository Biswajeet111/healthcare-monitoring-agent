from functools import lru_cache
from pathlib import Path
import pandas as pd
import joblib
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = PROJECT_ROOT / "models" / "health_risk_model.pkl"
SCALER_PATH = PROJECT_ROOT / "models" / "scaler.pkl"

FEATURE_NAMES = [
    "Pregnancies",
    "Glucose",
    "BloodPressure",
    "SkinThickness",
    "Insulin",
    "BMI",
    "DiabetesPedigreeFunction",
    "Age",
]


@lru_cache(maxsize=1)
def load_diabetes_model():
    """
    Load the locally trained diabetes classifier and scaler.

    Only load model files from trusted sources.
    """

    if not MODEL_PATH.is_file():
        raise FileNotFoundError("Diabetes model file not found")

    if not SCALER_PATH.is_file():
        raise FileNotFoundError("Diabetes scaler file not found")

    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)

    if getattr(model, "n_features_in_", None) != len(FEATURE_NAMES):
        raise ValueError("Unexpected model feature count")

    if getattr(scaler, "n_features_in_", None) != len(FEATURE_NAMES):
        raise ValueError("Unexpected scaler feature count")

    scaler_features = getattr(scaler, "feature_names_in_", None)

    if scaler_features is not None:
        if list(scaler_features) != FEATURE_NAMES:
            raise ValueError("Model preprocessing feature mismatch")

    if not hasattr(model, "predict_proba"):
        raise ValueError("Model does not support probability predictions")

    if list(getattr(model, "classes_", [])) != [0, 1]:
        raise ValueError("Unexpected model classes")

    return model, scaler


def predict_diabetes(features: dict):
    """
    Perform experimental diabetes risk screening.
    """

    model, scaler = load_diabetes_model()

    values = pd.DataFrame(
    [[features[name] for name in FEATURE_NAMES]],
    columns=FEATURE_NAMES,
    dtype=np.float64,
    )

    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("All input values must be finite")

    scaled_values = scaler.transform(values)

    predicted_class = int(model.predict(scaled_values)[0])

    probabilities = model.predict_proba(scaled_values)[0]

    positive_index = list(model.classes_).index(1)

    probability = float(probabilities[positive_index])

    return {
        "prediction": predicted_class,
        "model_score": round(probability, 4),
        "screening_result": (
            "Positive model classification"
            if predicted_class == 1
            else "Negative model classification"
        ),
        "model": "XGBoost",
        "model_version": "experimental-v1",
        "disclaimer": (
            "This is an experimental machine learning screening result, "
            "not a medical diagnosis. The model score is not a clinically "
            "calibrated probability. Consult a qualified healthcare "
            "professional for medical evaluation."
        ),
    }