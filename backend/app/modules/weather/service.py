import logging
import random
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.modules.weather.config import (
    WEATHER_API_TIMEOUT_S,
    WEATHER_ENDPOINT,
    WEATHER_FACTORS,
    WEATHER_FALLBACK_FACTOR,
)

logger = logging.getLogger(__name__)


def _openweather_to_category(
    cond_id: int, rain_mm: float, snow_mm: float,
) -> str:
    """Map OpenWeather condition id → internal WEATHER_FACTORS key.

    Ranges per openweathermap.org/weather-conditions.
    """
    if cond_id == 781:
        return "tornado"
    if cond_id == 511:
        return "freezing_rain"
    if 200 <= cond_id <= 232:
        return "thunderstorm"
    if 300 <= cond_id <= 321:
        return "light_rain"
    if 500 <= cond_id <= 531:
        if rain_mm >= 7.6 or cond_id in (502, 503, 504, 522):
            return "heavy_rain"
        if rain_mm >= 2.5 or cond_id in (501, 521, 531):
            return "moderate_rain"
        return "light_rain"
    if 600 <= cond_id <= 622:
        if cond_id in (611, 612, 613):
            return "freezing_rain"
        if snow_mm >= 2.5 or cond_id in (601, 602, 621, 622):
            return "heavy_snow"
        return "light_snow"
    if cond_id in (701, 711, 721, 731, 741, 751, 761, 762, 771):
        return "fog_low_vis"
    return "clear"


_STUB_CHOICES = [
    ("clear", 0.55),
    ("clear", 0.20),           # was "cloudy" — same factor
    ("light_rain", 0.10),
    ("heavy_rain", 0.05),
    ("light_snow", 0.05),
    ("fog_low_vis", 0.05),
]


@dataclass
class WeatherConditions:
    temperature_c: float
    condition: str
    wind_kmh: float
    source: str = field(default="stub")

    @property
    def weight_factor(self) -> float:
        return WEATHER_FACTORS.get(self.condition, WEATHER_FALLBACK_FACTOR)


class WeatherService:
    async def get_current(self, lat: float, lng: float) -> WeatherConditions:
        if settings.OPENWEATHER_API_KEY:
            try:
                return await self._fetch_openweather(lat, lng)
            except Exception:
                logger.warning("OpenWeather API failed, falling back to stub")

        choices, weights = zip(*_STUB_CHOICES)
        condition = random.choices(choices, weights=weights, k=1)[0]
        return WeatherConditions(
            temperature_c=round(random.uniform(5, 25), 1),
            condition=condition,
            wind_kmh=round(random.uniform(0, 20), 1),
            source="stub",
        )

    async def _fetch_openweather(
        self, lat: float, lng: float,
    ) -> WeatherConditions:
        async with httpx.AsyncClient(timeout=WEATHER_API_TIMEOUT_S) as client:
            resp = await client.get(WEATHER_ENDPOINT, params={
                "lat": lat,
                "lon": lng,
                "appid": settings.OPENWEATHER_API_KEY,
                "units": "metric",
            })
            resp.raise_for_status()
            data = resp.json()

        cond_id = int(data["weather"][0]["id"])
        main_weather = data["weather"][0]["main"]
        rain_mm = float(data.get("rain", {}).get("1h", 0.0))
        snow_mm = float(data.get("snow", {}).get("1h", 0.0))
        condition = _openweather_to_category(cond_id, rain_mm, snow_mm)
        temp_c = data["main"]["temp"]
        wind_ms = data.get("wind", {}).get("speed", 0)
        wind_kmh = round(wind_ms * 3.6, 1)

        logger.info(
            "OpenWeather: %s (id=%d) → %s, %.1f°C, wind %.1f km/h",
            main_weather, cond_id, condition, temp_c, wind_kmh,
        )
        return WeatherConditions(
            temperature_c=round(temp_c, 1),
            condition=condition,
            wind_kmh=wind_kmh,
            source="openweather",
        )
