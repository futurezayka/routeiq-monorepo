"""Polyline encoding / simplification configuration.

Precision 6 matches OSRM v4 / Valhalla / Mapzen (~10 cm at the equator);
precision 5 (~1 m) is the Google polyline-algorithm default. Tolerance
0.00005° ≈ 5.5 m at Kyiv latitude — fine for urban real-time routing.
"""

POLYLINE_PRECISION: int = 6
DP_TOLERANCE_DEG: float = 0.00005
