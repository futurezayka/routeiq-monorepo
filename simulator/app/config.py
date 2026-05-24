"""Defense-demo simulation configuration.

Values calibrated for the 20-minute defense presentation: 30 vehicles
hits a visual sweet-spot on the Kyiv map, telemetry every 5 s matches
PubNub's published Uber/Lyft tutorial cadence ("5000 ms ... 10 m
displacement"), and the rush-hour multiplier 0.55 produces a visible
~45% speed drop in the 08-10 and 17-19 windows.

Speed profile mirrors OSRM `car.lua` defaults with primary/secondary
adjusted for Kyiv urban conditions (slower than freeway defaults).
"""

N_VEHICLES: int = 30
TELEMETRY_INTERVAL_S: int = 5
RUSH_HOUR_WINDOWS: list[tuple[int, int]] = [(8, 10), (17, 19)]
RUSH_HOUR_SPEED_MULT: float = 0.55
INCIDENT_INJECT_INTERVAL_S: int = 180

SPEED_PROFILE_KMH: dict[str, int] = {
    "motorway":      90,
    "trunk":         85,
    "primary":       55,
    "secondary":     45,
    "tertiary":      35,
    "unclassified":  25,
    "residential":   25,
    "living_street": 10,
    "service":       15,
}
