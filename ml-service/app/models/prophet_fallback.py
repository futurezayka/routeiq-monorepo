import numpy as np
import pandas as pd


class ProphetFallback:
    """Prophet-based fallback predictor for segment traffic.

    Stub implementation — returns seasonal pattern based on hour-of-day.
    Will be replaced with a trained Prophet model per segment after history accumulates.
    """

    version: str = "prophet-stub-v1"

    def predict(self, segment_history: pd.DataFrame) -> pd.DataFrame:
        """Predict future congestion from historical data.

        Args:
            segment_history: DataFrame with columns [ds, y] where
                ds = timestamp, y = observed congestion level.

        Returns:
            DataFrame with columns [ds, yhat, yhat_lower, yhat_upper].
        """
        if segment_history.empty:
            return pd.DataFrame(columns=["ds", "yhat", "yhat_lower", "yhat_upper"])

        last_ts = pd.Timestamp(segment_history["ds"].max())
        future_periods = 24
        future_ts = pd.date_range(
            start=last_ts + pd.Timedelta(hours=1),
            periods=future_periods,
            freq="h",
        )

        hours = future_ts.hour.to_numpy(dtype=np.float32)
        base = 0.3 + 0.3 * np.sin((hours - 8) * np.pi / 12)
        noise = np.random.default_rng(seed=42).normal(0, 0.05, future_periods)
        yhat = np.clip(base + noise, 0, 1).astype(np.float32)

        return pd.DataFrame({
            "ds": future_ts,
            "yhat": yhat,
            "yhat_lower": np.clip(yhat - 0.1, 0, 1),
            "yhat_upper": np.clip(yhat + 0.1, 0, 1),
        })
