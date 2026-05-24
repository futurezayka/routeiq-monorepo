"""Train Isolation Forest on synthetic traffic dataset."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score

ROOT = Path(__file__).parent
DATASET = ROOT / "traffic_dataset.csv"
MODELS = ROOT.parent / "saved_models"


FEATURES = [
    "speed_kmh",
    "speed_ratio",       # speed_kmh / speed_limit
    "speed_zscore",      # deviation from (segment, hour) baseline in stddevs
    "rel_to_segment",    # speed_kmh / segment median (captures per-road slowdown)
]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["speed_ratio"] = df["speed_kmh"] / df["speed_limit"]

    # Baseline per (segment, hour) — captures typical speed at this hour on this road
    baseline = (
        df.groupby(["segment_id", "hour"])["speed_kmh"]
        .agg(["mean", "std"])
        .reset_index()
    )
    baseline.columns = ["segment_id", "hour", "baseline_mean", "baseline_std"]
    df = df.merge(baseline, on=["segment_id", "hour"], how="left")
    df["speed_zscore"] = (
        (df["speed_kmh"] - df["baseline_mean"])
        / (df["baseline_std"].fillna(1) + 1e-3)
    )

    # Per-segment median (across all hours) — slowdown indicator
    seg_median = df.groupby("segment_id")["speed_kmh"].median().rename("seg_median").reset_index()
    df = df.merge(seg_median, on="segment_id", how="left")
    df["rel_to_segment"] = df["speed_kmh"] / (df["seg_median"] + 1e-3)
    return df


def train() -> dict:
    df = pd.read_csv(DATASET)
    df = build_features(df)

    X = df[FEATURES].to_numpy()
    y = df["is_incident"].to_numpy()

    n_train = int(len(df) * 0.8)
    X_train, X_test = X[:n_train], X[n_train:]
    y_test = y[n_train:]

    # Lower contamination → fewer false positives.
    # True rate ~0.5%, so contamination 0.006 with strong features should be sharp.
    model = IsolationForest(
        n_estimators=300,
        contamination=0.006,
        max_samples=4096,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train)
    preds = (model.predict(X_test) == -1).astype(int)

    p = float(precision_score(y_test, preds, zero_division=0))
    r = float(recall_score(y_test, preds, zero_division=0))
    f1 = float(f1_score(y_test, preds, zero_division=0))
    print(f"Precision: {p:.3f}  Recall: {r:.3f}  F1: {f1:.3f}")
    print(f"  features: {FEATURES}")
    print(f"  test rows: {len(X_test):,}  true anomalies in test: {int(y_test.sum())}")
    print(f"  predicted anomalies: {int(preds.sum())}")

    MODELS.mkdir(exist_ok=True)
    joblib.dump(model, MODELS / "anomaly_v1.pkl")
    metrics = {
        "precision": p,
        "recall": r,
        "f1": f1,
        "test_samples": int(len(X_test)),
        "anomalies_in_test": int(y_test.sum()),
        "predicted_anomalies": int(preds.sum()),
        "n_estimators": 300,
        "contamination": 0.006,
        "features": FEATURES,
    }
    with (MODELS / "anomaly_metrics.json").open("w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved model to {MODELS / 'anomaly_v1.pkl'}")
    return metrics


if __name__ == "__main__":
    train()
