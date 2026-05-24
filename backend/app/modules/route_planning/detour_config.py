"""Detour-acceptance thresholds.

Per-severity caps on `new_distance / original_distance`. The lower bound
`MIN_TIME_SAVINGS_S = 60` mirrors GraphHopper's `distance_influence`
default (30 s/km) — refuse reroute when expected savings on the
remaining trip are below 60 s.
"""

DETOUR_MAX_RATIO: dict[str, float] = {
    "low":      1.20,
    "medium":   1.50,
    "high":     2.00,
    "critical": 3.00,
}

MIN_TIME_SAVINGS_S: int = 60
