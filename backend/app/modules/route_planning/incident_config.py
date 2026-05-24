"""Incident impact-zone configuration.

Values derived from HERE Traffic API v7 (`criticality` 4-tier) and TomTom
incident-radius-by-functionalClass conventions. TTLs match TomTom 1-min
refresh + median jam-lifetime, plus 2-h fallback for full closures
(matches Waze CIFS `endTime` semantics).
"""

IMPACT_RADIUS_M: dict[str, int] = {
    "low":      200,
    "medium":   400,
    "high":     800,
    "critical": 1500,
}

ROAD_TYPE_RADIUS_MULT: dict[str, float] = {
    "motorway":    2.0,
    "trunk":       1.7,
    "primary":     1.3,
    "secondary":   1.0,
    "tertiary":    0.8,
    "residential": 0.6,
    "service":     0.5,
}

INCIDENT_TTL_S: dict[str, int] = {
    "low":       900,
    "medium":   1800,
    "high":     3600,
    "critical": 7200,
}

INCIDENT_DECAY_HALF_LIFE_S: int = 300
INCIDENT_COOLDOWN_S: int = 600
REROUTING_SEARCH_RADIUS_M: int = 2500
