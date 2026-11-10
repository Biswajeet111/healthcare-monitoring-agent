"""Train and evaluate a candidate diabetes classifier without replacing v1.

Run from the project root:
    python -m healthguard.ml.train_diabetes
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, confusion_matrix, f1_score, precision_score,
    recall_score, roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / 'data' / 'diabetes.csv'
OUTPUT = ROOT / 'models' / 'diabetes_v2'
FEATURES = [
    'Pregnancies', 'Glucose', 'BloodPressure', 'SkinThickness',
    'Insulin', 'BMI', 'DiabetesPedigreeFunction', 'Age',
]
ZERO_MISSING = ['Glucose', 'BloodPressure', 'SkinThickness', 'Insulin', 'BMI']
OTHER = [name for name in FEATURES if name not in ZERO_MISSING]


def make_pipeline(classifier):
    # A zero in these five columns represents a missing/invalid measurement
    # in this dataset. Zero pregnancies is legitimate and is not imputed.
    preprocessing = ColumnTransformer(
        transformers=[
            ('zero_as_missing', SimpleImputer(missing_values=0, strategy='median'), ZERO_MISSING),
            ('other', SimpleImputer(strategy='median'), OTHER),
        ],
        remainder='drop',
    )
    return Pipeline([
        ('preprocessing', preprocessing),
        ('scaler', StandardScaler()),
        ('classifier', classifier),
    ])


def metrics(y_true, probabilities, threshold):
    predicted = (np.asarray(probabilities) >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()
    return {
        'accuracy': round(float(accuracy_score(y_true, predicted)), 4),
        'precision': round(float(precision_score(y_true, predicted, zero_division=0)), 4),
        'recall': round(float(recall_score(y_true, predicted, zero_division=0)), 4),
        'specificity': round(float(tn / (tn + fp)), 4) if tn + fp else None,
        'f1': round(float(f1_score(y_true, predicted, zero_division=0)), 4),
        'roc_auc': round(float(roc_auc_score(y_true, probabilities)), 4),
        'confusion_matrix': [[int(tn), int(fp)], [int(fn), int(tp)]],
    }


def main():
    if not DATASET.is_file():
        raise FileNotFoundError(f'Dataset missing: {DATASET}')
    data = pd.read_csv(DATASET)
    expected = set(FEATURES + ['Outcome'])
    if not expected.issubset(data.columns):
        raise ValueError(f'Missing columns: {sorted(expected - set(data.columns))}')
    if data[FEATURES].isna().any().any():
        print('Note: dataset contains NaN; median imputation will handle it.')
    if not set(data['Outcome'].unique()).issubset({0, 1}):
        raise ValueError('Outcome must contain only 0 and 1')
    X, y = data[FEATURES], data['Outcome'].astype(int)

    # 60% train / 20% validation / 20% untouched test.
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42,
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval, test_size=0.25, stratify=y_trainval, random_state=42,
    )
    print(f'Train={len(X_train)} Validation={len(X_val)} Test={len(X_test)}')

    candidates = {
        'LogisticRegression': LogisticRegression(max_iter=2000, random_state=42),
        'RandomForest': RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1),
        'GradientBoosting': GradientBoostingClassifier(random_state=42),
        'XGBoost': XGBClassifier(
            n_estimators=200, eval_metric='logloss', random_state=42,
            n_jobs=2, objective='binary:logistic',
        ),
    }
    results = []
    best = None
    thresholds = np.round(np.arange(0.20, 0.801, 0.05), 2)
    for name, estimator in candidates.items():
        pipeline = make_pipeline(estimator)
        pipeline.fit(X_train, y_train)
        scores = pipeline.predict_proba(X_val)[:, 1]
        for threshold in thresholds:
            val_metrics = metrics(y_val, scores, float(threshold))
            # Demonstration-only selection criterion, NOT a clinical threshold.
            if val_metrics['specificity'] is None or val_metrics['specificity'] < 0.70:
                continue
            rank = (val_metrics['recall'], val_metrics['f1'], val_metrics['specificity'])
            entry = {'model': name, 'threshold': float(threshold), 'validation': val_metrics}
            results.append(entry)
            if best is None or rank > best[0]:
                best = (rank, pipeline, entry)
        print(f'Validated: {name}')

    if best is None:
        raise RuntimeError('No candidate met the demonstration specificity constraint')
    _, selected_pipeline, selection = best
    threshold = selection['threshold']
    # Evaluate once on untouched test; do not tune after seeing this result.
    test_scores = selected_pipeline.predict_proba(X_test)[:, 1]
    test_metrics = metrics(y_test, test_scores, threshold)
    report = {
        'model_version': 'experimental-v2-candidate',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'dataset': str(DATASET.relative_to(ROOT)),
        'dataset_rows': len(data),
        'split': {'train': len(X_train), 'validation': len(X_val), 'test': len(X_test)},
        'features': FEATURES,
        'zero_treated_as_missing': ZERO_MISSING,
        'selection_rule': 'Highest validation recall with validation specificity >= 0.70; F1 and specificity break ties',
        'selected_model': selection['model'],
        'threshold': threshold,
        'validation_metrics': selection['validation'],
        'test_metrics': test_metrics,
        'limitations': [
            'Exploratory PIMA dataset model, not clinically validated.',
            'Decision threshold chosen for demonstration, not medical use.',
            'Held-out test set must not be used to revise selection.',
            'Training data and evaluation come from the same dataset/source.',
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    joblib.dump(selected_pipeline, OUTPUT / 'pipeline.joblib')
    (OUTPUT / 'evaluation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('\nSelected:', selection['model'], 'Threshold:', threshold)
    print('Validation:', json.dumps(selection['validation'], indent=2))
    print('Untouched test:', json.dumps(test_metrics, indent=2))
    print('Saved candidate to:', OUTPUT)
    print('Existing v1 model and API were NOT modified.')


if __name__ == '__main__':
    main()
