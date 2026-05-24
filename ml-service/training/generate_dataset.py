"""Generate realistic synthetic traffic dataset for Kyiv-like patterns."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "traffic_dataset.csv"


def generate(num_segments: int = 50, days: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    start = datetime(2026, 4, 1)

    segments = [
        {
            "id": f"seg_{i:03d}",
            "speed_limit": int(rng.choice([50, 60, 80])),
            "base_factor": float(rng.uniform(0.75, 1.0)),
            "rush_sensitivity": float(rng.uniform(0.6, 1.4)),
        }
        for i in range(num_segments)
    ]

    records: list[dict] = []
    for d in range(days):
        for h in range(24):
            for m in (0, 15, 30, 45):
                ts = start + timedelta(days=d, hours=h, minutes=m)
                dow = ts.weekday()
                is_weekend = dow >= 5

                # rush hour factor: 0.3 = heavy traffic, 1.0 = free flow
                if 7 <= h < 10 and not is_weekend:
                    rush = 0.4 + 0.15 * np.sin((h - 7) * np.pi / 3)
                elif 17 <= h < 20 and not is_weekend:
                    rush = 0.3 + 0.2 * np.sin((h - 17) * np.pi / 3)
                elif h >= 22 or h < 6:
                    rush = 1.0
                else:
                    rush = 0.8 if not is_weekend else 0.95

                weather = float(rng.choice([1.0, 0.9, 0.75, 0.55], p=[0.6, 0.2, 0.15, 0.05]))

                for seg in segments:
                    base = seg["speed_limit"] * seg["base_factor"]
                    speed = base * rush * weather * seg["rush_sensitivity"]
                    speed += rng.normal(0, 2.5)

                    is_inc = float(rng.random()) < 0.005
                    if is_inc:
                        speed *= 0.2

                    records.append({
                        "timestamp": ts,
                        "segment_id": seg["id"],
                        "speed_kmh": max(2.0, float(speed)),
                        "speed_limit": seg["speed_limit"],
                        "hour": h,
                        "day_of_week": dow,
                        "is_weekend": int(is_weekend),
                        "weather_factor": weather,
                        "is_incident": int(is_inc),
                    })

    df = pd.DataFrame(records)
    OUT.parent.mkdir(exist_ok=True)
    df.to_csv(OUT, index=False)
    print(
        f"Generated {len(df):,} records  "
        f"segments={num_segments}  days={days}  "
        f"anomalies={int(df['is_incident'].sum())} "
        f"(rate={df['is_incident'].mean()*100:.2f}%)"
    )
    return df


if __name__ == "__main__":
    generate()
