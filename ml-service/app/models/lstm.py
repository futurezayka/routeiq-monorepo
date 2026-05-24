"""Real LSTM traffic predictor.

Loads checkpoint produced by `training/train_lstm.py`. At inference time the
worker passes a 1-D `segment_data` (one feature per segment — currently
"average speed" or similar proxy). The trained model expects a 96-step,
6-feature window per segment, so we synthesize that window from:
  - the current speed proxy (broadcast across the 24h history),
  - real-time hour-of-day / day-of-week (sin/cos encoded),
  - a default weather factor of 1.0 (clear).
The model then produces predictions for 1h / 3h / 6h horizons in km/h.
We surface the 1h horizon as `avg_speed_kmh`, derive `congestion` from it,
and report a confidence based on horizon agreement.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import numpy as np
import torch
from torch import nn

logger = logging.getLogger(__name__)


class LSTMNet(nn.Module):
    def __init__(
        self,
        input_size: int = 6,
        hidden_size: int = 64,
        num_layers: int = 2,
        output_size: int = 3,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size, hidden_size, num_layers, batch_first=True, dropout=0.2,
        )
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :])


class TrafficPredictor:
    """LSTM-backed traffic predictor.

    `version` reflects whether the trained checkpoint loaded or we fell back
    to the stub.
    """

    DEFAULT_MODEL_PATH = "saved_models/lstm_v1.pt"
    FREE_FLOW_KMH = 60.0  # used to convert predicted speed → congestion fraction

    def __init__(self, model_path: str | None = None) -> None:
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model: LSTMNet | None = None
        self._input_window: int = 96
        self._horizons: list[int] = [4, 12, 24]
        self.version = "lstm-stub-v1"

        path = model_path or self.DEFAULT_MODEL_PATH
        try:
            if os.path.exists(path):
                ckpt = torch.load(path, map_location=self._device, weights_only=False)
                self._model = LSTMNet(
                    input_size=ckpt.get("input_size", 6),
                    hidden_size=ckpt.get("hidden_size", 64),
                    num_layers=ckpt.get("num_layers", 2),
                    output_size=ckpt.get("output_size", 3),
                )
                self._model.load_state_dict(ckpt["model_state"])
                self._model.to(self._device).eval()
                self._input_window = int(ckpt.get("input_window", 96))
                self._horizons = list(ckpt.get("horizons", [4, 12, 24]))
                self.version = "lstm-v1"
                logger.info(
                    "LSTM loaded: %s (window=%d, horizons=%s, device=%s)",
                    path, self._input_window, self._horizons, self._device,
                )
            else:
                logger.warning("LSTM checkpoint not found at %s — using stub", path)
        except Exception:
            logger.exception("Failed to load LSTM checkpoint — using stub")
            self._model = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def _build_window(self, segment_speeds: np.ndarray) -> np.ndarray:
        """Synthesize an (N, 96, 6) input batch from current per-segment speeds."""
        now = datetime.now()
        hour = now.hour + now.minute / 60.0
        dow = now.weekday()

        # Static time/weather columns are the same for every step in the window.
        hour_sin = float(np.sin(2 * np.pi * hour / 24))
        hour_cos = float(np.cos(2 * np.pi * hour / 24))
        dow_sin = float(np.sin(2 * np.pi * dow / 7))
        dow_cos = float(np.cos(2 * np.pi * dow / 7))
        weather = 1.0  # default clear; can be wired from Redis weather factor

        N = len(segment_speeds)
        W = self._input_window
        x = np.zeros((N, W, 6), dtype=np.float32)
        # Speed channel normalised by 100 (consistent with training)
        x[:, :, 0] = (segment_speeds.reshape(-1, 1) / 100.0).astype(np.float32)
        x[:, :, 1] = hour_sin
        x[:, :, 2] = hour_cos
        x[:, :, 3] = dow_sin
        x[:, :, 4] = dow_cos
        x[:, :, 5] = weather
        return x

    def predict(self, segment_data: np.ndarray) -> np.ndarray:
        """Return per-segment (congestion, avg_speed_kmh, confidence).

        segment_data: 1-D array of current speed proxies (km/h), one per segment.
        Output shape: (N, 3) where columns are
          [0] congestion fraction in [0, 1] (higher = more congested),
          [1] predicted avg_speed_kmh at the nearest horizon (≈1h),
          [2] confidence in [0, 1].
        """
        speeds = np.asarray(segment_data, dtype=np.float32).reshape(-1)
        n = len(speeds)
        if n == 0:
            return np.zeros((0, 3), dtype=np.float32)

        if self._model is None:
            # Fallback: deterministic stub matching trained semantics.
            rng = np.random.default_rng(seed=42)
            congestion = np.clip(0.3 + speeds * 0.01 + rng.normal(0, 0.05, n), 0, 1)
            avg_speed = np.clip(45.0 - congestion * 30, 10, 60)
            confidence = np.full(n, 0.5, dtype=np.float32)
            return np.column_stack([congestion, avg_speed, confidence]).astype(np.float32)

        # Build synthetic windows and run real LSTM.
        x = self._build_window(speeds)
        with torch.no_grad():
            tensor = torch.from_numpy(x).to(self._device)
            raw = self._model(tensor).cpu().numpy()  # shape (N, 3) in normalised speed
        predicted_speeds = raw * 100.0  # de-normalise

        # 1h horizon is the first output column
        avg_speed = np.clip(predicted_speeds[:, 0], 1.0, 120.0)
        congestion = np.clip(1.0 - avg_speed / self.FREE_FLOW_KMH, 0.0, 1.0)

        # Confidence: 1 - normalised spread across horizons (lower spread → higher confidence)
        spread = np.std(predicted_speeds, axis=1) / (np.mean(predicted_speeds, axis=1) + 1e-6)
        confidence = np.clip(1.0 - spread, 0.3, 0.99).astype(np.float32)

        return np.column_stack([
            congestion.astype(np.float32),
            avg_speed.astype(np.float32),
            confidence,
        ])
