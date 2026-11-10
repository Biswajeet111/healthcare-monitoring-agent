"""Assess two PIMA diabetes model finalists on development data only.

Run: python -m healthguard.ml.assess_diabetes_finalists
No existing model artifacts or APIs are modified.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score, confusion_matrix
from sklearn.model_selection import RepeatedStratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ['Pregnancies', 'Glucose', 'BloodPressure', 'SkinThickness', 'Insulin', 'BMI', 'DiabetesPedigreeFunction', 'Age']
ZERO_MISSING = ['Glucose', 'BloodPressure', 'SkinThickness', 'Insulin', 'BMI']
OTHER = [f for f in FEATURES if f not in ZERO_MISSING]


def make_pipeline(name):
    indicators = name == 'GradientBoosting_with_indicators'
    preprocess = ColumnTransformer([
        ('zero_as_missing', SimpleImputer(missing_values=0, strategy='median', add_indicator=indicators), ZERO_MISSING),
        ('other', SimpleImputer(strategy='median'), OTHER),
    ])
    clf = (LogisticRegression(max_iter=2000, random_state=42)
           if name == 'LogisticRegression' else GradientBoostingClassifier(random_state=42))
    return Pipeline([('preprocessing', preprocess), ('scaler', StandardScaler()), ('classifier', clf)])


def operating_metrics(y, scores, threshold):
    pred = (scores >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {'recall': float(tp / (tp + fn)) if tp + fn else None,
            'specificity': float(tn / (tn + fp)) if tn + fp else None,
            'precision': float(tp / (tp + fp)) if tp + fp else None,
            'false_positives': int(fp), 'false_negatives': int(fn)}


def main():
    df = pd.read_csv(ROOT / 'data' / 'diabetes.csv')
    X, y = df[FEATURES], df['Outcome'].astype(int)
    # Match original v2 outer split; NEVER access the held-out 20% test partition.
    X_dev, _, y_dev, _ = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=3, random_state=2026)
    report = {'created_utc': datetime.now(timezone.utc).isoformat(),
              'development_rows': len(X_dev), 'cv': '5 folds x 3 repeats',
              'note': 'Exploratory repeated CV on development partition only. Fold scores are correlated; no independent external validation.',
              'models': {}}
    for name in ('LogisticRegression', 'GradientBoosting_with_indicators'):
        fold_rows = []
        for fold, (tr, va) in enumerate(cv.split(X_dev, y_dev), start=1):
            pipe = make_pipeline(name)
            pipe.fit(X_dev.iloc[tr], y_dev.iloc[tr])
            scores = pipe.predict_proba(X_dev.iloc[va])[:, 1]
            truth = y_dev.iloc[va].to_numpy()
            fold_rows.append({'fold': fold,
                              'roc_auc': float(roc_auc_score(truth, scores)),
                              'brier': float(brier_score_loss(truth, scores)),
                              'thresholds': {f'{t:.2f}': operating_metrics(truth, scores, float(t))
                                             for t in np.arange(0.20, 0.501, 0.05)}})
        summary = {}
        for metric in ('roc_auc', 'brier'):
            values = np.array([r[metric] for r in fold_rows])
            summary[metric] = {'mean': round(float(values.mean()), 4),
                               'std': round(float(values.std(ddof=1)), 4)}
        for threshold in ('0.25', '0.30', '0.35', '0.40', '0.45', '0.50'):
            for metric in ('recall', 'specificity'):
                values = np.array([r['thresholds'][threshold][metric] for r in fold_rows])
                summary[f'{metric}_at_{threshold}'] = {'mean': round(float(values.mean()), 4),
                                                      'std': round(float(values.std(ddof=1)), 4)}
        report['models'][name] = {'summary': summary, 'folds': fold_rows}
        print(f'\n{name}: AUC {summary["roc_auc"]}, Brier {summary["brier"]}')
        for t in ('0.25', '0.30', '0.35', '0.40', '0.50'):
            print(f'  threshold {t}: recall {summary[f"recall_at_{t}"]}, specificity {summary[f"specificity_at_{t}"]}')
    out = ROOT / 'models' / 'diabetes_validation' / 'finalist_assessment.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('\nSaved:', out)
    print('Existing models and APIs unchanged.')


if __name__ == '__main__':
    main()
