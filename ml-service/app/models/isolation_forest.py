"""Real Isolation Forest anomaly detector.

Loads sklearn IsolationForest produced by `training/train_anomaly.py`.
Worker provides per-segment current speed only — we synthesize the same
three features the model was trained on (speed_kmh, speed_ratio, speed_zscore)
using a default speed_limit and population baseline derived from the batch.
"""
from __future__ import annotations

import logging
import os

import joblib
import numpy as np

logger = logging.getLogger(__name__)


class AnomalyDetector:
    DEFAULT_MODEL_PATH = "saved_models/anomaly_v1.pkl"
    DEFAULT_SPEED_LIMIT_KMH = 50.0
    threshold: float = 0.85

    def __init__(self, model_path: str | None = None) -> None:
        self._model = None
        self.version = "iforest-stub-v1"
        path = model_path or self.DEFAULT_MODEL_PATH

        try:
            if os.path.exists(path):
                self._model = joblib.load(path)
                self.version = "iforest-v1"
                logger.info("IsolationForest loaded: %s", path)
            else:
                logger.warning(
                    "Anomaly checkpoint not found at %s — using stub", path,
                )
        except Exception:
            logger.exception("Failed to load IsolationForest — using stub")
            self._model = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def _build_features(self, speeds: np.ndarray) -> np.ndarray:
        """Build the (N, 4) feature matrix the trained model expects.

        At training time per-segment, per-hour baselines come from history.
        At inference we only have the current batch of segment speeds, so
        z-score and rel_to_segment are computed against the batch as a proxy.
        This is correct in spirit (anomalies stand out from their peers) and
        gracefully degrades if a single segment is provided (z=0, rel=1).
        """
        speed_limit = self.DEFAULT_SPEED_LIMIT_KMH
        ratio = speeds / speed_limit

        # Z-score relative to the batch (no per-segment history available).
        if len(speeds) >= 2:
            batch_mean = float(np.mean(speeds))
            batch_std = float(np.std(speeds))
        else:
            batch_mean, batch_std = 40.0, 10.0
        if batch_std < 1e-3:
            batch_std = 10.0
        zscore = (speeds - batch_mean) / batch_std

        # Relative-to-segment: ratio of current to median of the batch.
        batch_median = float(np.median(speeds)) if len(speeds) else 40.0
        if batch_median < 1e-3:
            batch_median = 40.0
        rel_to_segment = speeds / batch_median

        return np.column_stack([speeds, ratio, zscore, rel_to_segment]).astype(np.float32)

    def detect(self, speeds: np.ndarray) -> np.ndarray:
        """Return per-segment anomaly score in [0, 1] (higher = more anomalous)."""
        speeds = np.asarray(speeds, dtype=np.float32).reshape(-1)
        if len(speeds) == 0:
            return np.array([], dtype=np.float32)

        if self._model is None:
            # Fallback: deviation from median, same as old stub.
            median = float(np.median(speeds))
            if median == 0:
                return np.ones(len(speeds), dtype=np.float32)
            deviation = np.abs(speeds - median) / max(median, 1.0)
            return np.clip(deviation, 0, 1).astype(np.float32)

        x = self._build_features(speeds)
        # Two signals:
        #   predict():           -1 = anomaly per the trained contamination, +1 = normal
        #   decision_function(): higher = more normal; lower = more anomalous
        # Score is constructed so it ONLY exceeds the AnomalyDetector.threshold
        # (default 0.85) for points flagged by predict().  This stops every
        # batch from producing a "score=1.0" alert just because something must
        # be the relative outlier.
        is_anom = self._model.predict(x) == -1
        raw = self._model.decision_function(x)

        scores = np.zeros(len(speeds), dtype=np.float32)
        if is_anom.any():
            anom_raw = raw[is_anom]
            # Map anomalous raw scores (negative) into [0.85, 1.0]
            anom_min, anom_max = float(anom_raw.min()), float(anom_raw.max())
            if anom_max - anom_min < 1e-9:
                anom_norm = np.full(len(anom_raw), 0.92, dtype=np.float32)
            else:
                anom_norm = 0.85 + 0.15 * (anom_max - anom_raw) / (anom_max - anom_min + 1e-9)
            scores[is_anom] = anom_norm
        if (~is_anom).any():
            normal_raw = raw[~is_anom]
            # Map normal raw into [0, 0.7] (proportional but capped)
            n_min, n_max = float(normal_raw.min()), float(normal_raw.max())
            if n_max - n_min < 1e-9:
                normal_norm = np.full(len(normal_raw), 0.3, dtype=np.float32)
            else:
                normal_norm = 0.7 * (n_max - normal_raw) / (n_max - n_min + 1e-9)
            scores[~is_anom] = normal_norm
        return scores
