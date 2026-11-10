"""Development-only cross-validation for HealthGuard diabetes candidates.

Run from project root:
    python -m healthguard.ml.validate_diabetes

Uses only the 80% development partition from train_diabetes.py. Does NOT
inspect the held-out 20% test partition or replace any model artifacts.
"""
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, brier_score_loss, confusion_matrix, f1_score,
    precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / 'data' / 'diabetes.csv'
OUTPUT = ROOT / 'models' / 'diabetes_validation'
FEATURES = [
    'Pregnancies', 'Glucose', 'BloodPressure', 'SkinThickness',
    'Insulin', 'BMI', 'DiabetesPedigreeFunction', 'Age',
]
ZERO_MISSING = ['Glucose', 'BloodPressure', 'SkinThickness', 'Insulin', 'BMI']
OTHER = [x for x in FEATURES if x not in ZERO_MISSING]
THRESHOLDS = [round(float(x), 2) for x in np.arange(0.20, 0.801, 0.05)]


def pipeline_for(model, indicators):
    zero_imputer = SimpleImputer(
        missing_values=0, strategy='median', add_indicator=indicators,
    )
    prep = ColumnTransformer([
        ('zero_as_missing', zero_imputer, ZERO_MISSING),
        ('other', SimpleImputer(strategy='median'), OTHER),
    ])
    return Pipeline([
        ('preprocessing', prep),
        ('scaler', StandardScaler()),
        ('classifier', model),
    ])


def scores_at(y, probabilities, threshold):
    pred = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        'threshold': threshold,
        'accuracy': round(float(accuracy_score(y, pred)), 4),
        'precision': round(float(precision_score(y, pred, zero_division=0)), 4),
        'recall': round(float(recall_score(y, pred, zero_division=0)), 4),
        'specificity': round(float(tn / (tn + fp)), 4) if tn + fp else None,
        'f1': round(float(f1_score(y, pred, zero_division=0)), 4),
        'confusion_matrix': [[int(tn), int(fp)], [int(fn), int(tp)]],
    }


def main():
    if not DATASET.is_file():
        raise FileNotFoundError(f'Missing dataset: {DATASET}')
    data = pd.read_csv(DATASET)
    required = FEATURES + ['Outcome']
    if not set(required).issubset(data.columns):
        raise ValueError(f'Missing columns: {sorted(set(required) - set(data.columns))}')
    if data[required].isna().any().any():
        raise ValueError('Unexpected NaNs in dataset; review missing-data policy first')
    if not set(data['Outcome'].unique()) == {0, 1}:
        raise ValueError('Outcome must contain both 0 and 1 only')

    X, y = data[FEATURES], data['Outcome'].astype(int)
    # EXACT same outer split as train_diabetes.py; held-out test is discarded.
    X_dev, _, y_dev, _ = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42,
    )
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    models = {
        'LogisticRegression': lambda: LogisticRegression(max_iter=2000, random_state=42),
        'RandomForest': lambda: RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=1),
        'GradientBoosting': lambda: GradientBoostingClassifier(random_state=42),
        'XGBoost': lambda: XGBClassifier(
            n_estimators=200, eval_metric='logloss', random_state=42,
            n_jobs=1, objective='binary:logistic',
        ),
    }
    results = []
    for model_name, factory in models.items():
        for indicators in (False, True):
            candidate = pipeline_for(factory(), indicators)
            # Each fold refits imputation/scaling/classifier on fold-training only.
            oof_prob = cross_val_predict(
                candidate, X_dev, y_dev, cv=cv, method='predict_proba', n_jobs=1,
            )[:, 1]
            threshold_results = [scores_at(y_dev, oof_prob, t) for t in THRESHOLDS]
            feasible = [r for r in threshold_results if r['specificity'] is not None and r['specificity'] >= 0.70]
            selected = max(feasible, key=lambda r: (r['recall'], r['f1'], r['specificity'])) if feasible else None
            row = {
                'model': model_name,
                'missingness_indicators': indicators,
                'oof_roc_auc': round(float(roc_auc_score(y_dev, oof_prob)), 4),
                'oof_brier_score': round(float(brier_score_loss(y_dev, oof_prob)), 4),
                'threshold_results': threshold_results,
                'best_under_demo_constraint': selected,
            }
            results.append(row)
            selected_str = f"threshold={selected['threshold']}, recall={selected['recall']}, specificity={selected['specificity']}" if selected else 'no feasible threshold'
            print(f'{model_name:20} indicators={str(indicators):5} AUC={row["oof_roc_auc"]:.4f} Brier={row["oof_brier_score"]:.4f} | {selected_str}')

    eligible = [r for r in results if r['best_under_demo_constraint']]
    winner = max(
        eligible,
        key=lambda r: (
            r['best_under_demo_constraint']['recall'],
            r['best_under_demo_constraint']['f1'],
            r['best_under_demo_constraint']['specificity'],
        ),
    ) if eligible else None
    report = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'dataset_sha256': hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        'dataset_rows': len(data),
        'development_rows': len(X_dev),
        'held_out_test_rows_not_used': len(data) - len(X_dev),
        'cv': 'StratifiedKFold(n_splits=5, shuffle=True, random_state=42)',
        'selection_constraint': 'Development-only heuristic: specificity >= 0.70',
        'versions': {
            'python': platform.python_version(), 'numpy': np.__version__,
            'pandas': pd.__version__, 'scikit_learn': sklearn.__version__,
            'xgboost': xgboost.__version__,
        },
        'results': results,
        'exploratory_winner': {
            'model': winner['model'],
            'missingness_indicators': winner['missingness_indicators'],
            'operating_point': winner['best_under_demo_constraint'],
        } if winner else None,
        'limitations': [
            'Out-of-fold predictions are used for both threshold selection and reported metrics; selected metrics are optimistic.',
            'These results are development comparisons, not independent final performance estimates.',
            'The prior v2 test set has already been examined and must not be reused to claim an unbiased final evaluation.',
            'PIMA population is not representative of general clinical populations; not for diagnosis.',
            'No calibration or external validation has been performed.',
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / 'cv_comparison.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('\nExploratory winner:', json.dumps(report['exploratory_winner'], indent=2))
    print('Saved:', path)
    print('No existing model files or APIs were modified.')


if __name__ == '__main__':
    main()
