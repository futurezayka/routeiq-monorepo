"""Weather multiplier and OpenWeather integration configuration.

Multiplier values anchored to FHWA Road Weather Management and
Smith 2004 ("Empirical Studies on Traffic Flow in Inclement Weather",
FHWA / NTL). Endpoint is OpenWeather Current Weather v2.5 (free tier:
60 calls/min, 1 000 000 calls/month, model updates every 10 minutes —
hence 600 s cache TTL). Do NOT switch to One Call 3.0: it requires a
credit card on file even for its 1 000-call/day free band.
"""

WEATHER_FACTORS: dict[str, float] = {
    "clear":         1.00,
    "light_rain":    1.05,   # < 2.5 mm/h
    "moderate_rain": 1.10,   # 2.5-7.5 mm/h
    "heavy_rain":    1.25,   # > 7.5 mm/h (FHWA: freeway speed -16%)
    "light_snow":    1.15,   # FHWA: 3-13% freeway speed reduction
    "heavy_snow":    1.40,   # FHWA: up to 40% arterial speed reduction
    "fog_low_vis":   1.20,   # visibility < 200 m
    "freezing_rain": 1.60,   # OpenWeather id=511
    "thunderstorm":  1.40,
    "tornado":       5.00,   # OpenWeather id=781 — effective block
}

WEATHER_ENDPOINT: str = "https://api.openweathermap.org/data/2.5/weather"
WEATHER_CACHE_TTL_S: int = 600
WEATHER_API_TIMEOUT_S: int = 3
WEATHER_FALLBACK_FACTOR: float = 1.0
