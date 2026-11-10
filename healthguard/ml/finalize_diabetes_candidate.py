"""Fit a frozen experimental diabetes candidate on development data only.

Run: python -m healthguard.ml.finalize_diabetes_candidate
Does not read the held-out test labels or replace the existing v1/v2 artifacts.
"""
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from healthguard.ml.train_diabetes import FEATURES, ROOT, DATASET, make_pipeline

OUTPUT = ROOT / "models" / "diabetes_v3_candidate"
THRESHOLD = 0.30


def main():
    if not DATASET.is_file():
        raise FileNotFoundError(f"Dataset missing: {DATASET}")
    data = pd.read_csv(DATASET)
    required = FEATURES + ["Outcome"]
    if any(column not in data.columns for column in required):
        raise ValueError("Dataset is missing required columns")
    if data[required].isna().any().any():
        raise ValueError("Unexpected NaNs in source dataset; review before fitting")
    if not set(data["Outcome"].unique()).issubset({0, 1}):
        raise ValueError("Outcome must contain only 0 and 1")
    if not np.isfinite(data[required].to_numpy(dtype=float)).all():
        raise ValueError("Dataset contains nonfinite values")

    X, y = data[FEATURES], data["Outcome"].astype(int)
    X_dev, _X_holdout, y_dev, _y_holdout = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42
    )
    pipeline = make_pipeline(LogisticRegression(max_iter=2000, random_state=42))
    pipeline.fit(X_dev, y_dev)
    probe = pipeline.predict_proba(X_dev.iloc[:2])
    if probe.shape != (2, 2) or not np.isfinite(probe).all():
        raise RuntimeError("Saved pipeline failed inference smoke test")

    metadata = {
        "model_version": "experimental-v3-candidate",
        "model": "LogisticRegression",
        "threshold": THRESHOLD,
        "threshold_selection": "Preselected from development-only repeated CV; not clinically validated",
        "feature_names": FEATURES,
        "development_rows": len(X_dev),
        "holdout_rows_not_used": len(_X_holdout),
        "source_dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "warning": "Experimental classification only; not a diagnosis or validated individual risk estimate.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    model_path = OUTPUT / "pipeline.joblib"
    metadata_path = OUTPUT / "metadata.json"
    if model_path.exists() or metadata_path.exists():
        raise FileExistsError(f"Candidate already exists in {OUTPUT}; do not silently overwrite it")
    joblib.dump(pipeline, model_path)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    restored = joblib.load(model_path)  # Load only our locally created trusted artifact.
    if not np.allclose(restored.predict_proba(X_dev.iloc[:2]), probe):
        raise RuntimeError("Reloaded model predictions differ")
    print(f"Saved frozen candidate: {model_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Development rows: {len(X_dev)}; excluded holdout rows: {len(_X_holdout)}")
    print(f"Threshold: {THRESHOLD}")
    print("No held-out test metrics computed; existing API and models unchanged.")


if __name__ == "__main__":
    main()
