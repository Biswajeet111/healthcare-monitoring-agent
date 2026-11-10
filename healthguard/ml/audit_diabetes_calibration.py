"""Development-only calibration audit for HealthGuard AI diabetes finalists.

Run: python -m healthguard.ml.audit_diabetes_calibration
Does not fit on or inspect the reserved 20% test partition.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier

from healthguard.ml.train_diabetes import FEATURES, make_pipeline

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data' / 'diabetes.csv'
OUT = ROOT / 'models' / 'diabetes_validation' / 'calibration_audit.json'


def summarize(y, probabilities, threshold=0.30):
    predictions = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, predictions, labels=[0, 1]).ravel()
    fraction_positive, mean_predicted = calibration_curve(
        y, probabilities, n_bins=8, strategy='quantile'
    )
    return {
        'roc_auc': round(float(roc_auc_score(y, probabilities)), 4),
        'brier': round(float(brier_score_loss(y, probabilities)), 4),
        'log_loss': round(float(log_loss(y, probabilities, labels=[0, 1])), 4),
        'threshold': threshold,
        'recall': round(float(tp / (tp + fn)), 4) if tp + fn else None,
        'specificity': round(float(tn / (tn + fp)), 4) if tn + fp else None,
        'precision': round(float(tp / (tp + fp)), 4) if tp + fp else None,
        'confusion_matrix': [[int(tn), int(fp)], [int(fn), int(tp)]],
        'calibration_bins': [
            {'mean_predicted': round(float(p), 4), 'observed_fraction': round(float(o), 4)}
            for p, o in zip(mean_predicted, fraction_positive)
        ],
    }


def main():
    raw = DATA.read_bytes()
    frame = pd.read_csv(DATA)
    X, y = frame[FEATURES], frame['Outcome'].astype(int)
    X_dev, _, y_dev, _ = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42
    )
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    finalists = {
        'LogisticRegression': make_pipeline(
            LogisticRegression(max_iter=2000, random_state=42)
        ),
    }
    results = {}
    for name, pipeline in finalists.items():
        # Every held-out fold is predicted by a pipeline fitted only on other folds.
        scores = cross_val_predict(
            pipeline, X_dev, y_dev, cv=cv, method='predict_proba', n_jobs=1
        )[:, 1]
        results[name] = summarize(y_dev.to_numpy(), scores)
        print(f'\n{name} — development-only out-of-fold audit')
        print(json.dumps(results[name], indent=2))

    report = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'dataset_sha256': hashlib.sha256(raw).hexdigest(),
        'sklearn_version': sklearn.__version__,
        'development_rows': int(len(X_dev)),
        'reserved_test_rows_not_used': int(len(X) - len(X_dev)),
        'cv': 'StratifiedKFold(n_splits=5, shuffle=True, random_state=42)',
        'threshold': 0.30,
        'results': results,
        'limitations': [
            'Exploratory calibration assessment on one dataset; not external validation.',
            'Threshold 0.30 was considered during earlier development and is not independent.',
            'Calibration bins are descriptive, not proof of clinical calibration.',
            'Do not interpret scores as individual clinical disease probabilities.',
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'\nSaved: {OUT}')
    print('No model artifacts, API endpoints, or reserved test records changed.')


if __name__ == '__main__':
    main()
