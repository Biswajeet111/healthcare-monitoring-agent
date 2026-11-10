from pathlib import Path

import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
    classification_report,
)
from sklearn.model_selection import train_test_split

from healthguard.ml.diabetes_predictor import (
    FEATURE_NAMES,
    load_diabetes_model,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / "data" / "diabetes.csv"


def evaluate_model():
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATASET_PATH}"
        )

    df = pd.read_csv(DATASET_PATH)

    required_columns = FEATURE_NAMES + ["Outcome"]

    if not set(required_columns).issubset(df.columns):
        raise ValueError("Dataset is missing required columns")

    X = df[FEATURE_NAMES]
    y = df["Outcome"]

    _, X_test, _, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )

    model, scaler = load_diabetes_model()

    X_test_scaled = scaler.transform(X_test)

    predictions = model.predict(X_test_scaled)
    probabilities = model.predict_proba(X_test_scaled)[:, 1]

    tn, fp, fn, tp = confusion_matrix(
        y_test,
        predictions,
        labels=[0, 1],
    ).ravel()

    specificity = tn / (tn + fp) if (tn + fp) else 0

    print("\n===== HealthGuard AI — Diabetes Model Evaluation =====")

    print(f"Accuracy:    {accuracy_score(y_test, predictions):.4f}")
    print(f"Precision:   {precision_score(y_test, predictions, zero_division=0):.4f}")
    print(f"Recall:      {recall_score(y_test, predictions, zero_division=0):.4f}")
    print(f"Specificity: {specificity:.4f}")
    print(f"F1-score:    {f1_score(y_test, predictions, zero_division=0):.4f}")
    print(f"ROC-AUC:     {roc_auc_score(y_test, probabilities):.4f}")

    print("\nConfusion Matrix:")
    print(confusion_matrix(y_test, predictions, labels=[0, 1]))

    print("\nClassification Report:")
    print(classification_report(y_test, predictions, zero_division=0))

    print(
        "\nNOTE: These metrics reproduce the original exploratory "
        "test split. This is not an independent validation because "
        "the split was used during model selection."
    )


if __name__ == "__main__":
    evaluate_model()