import asyncio
import logging

from redis.asyncio import Redis

from app.modules.route_planning.graph_weights import GraphWeightManager
from app.modules.weather.service import WeatherService

logger = logging.getLogger(__name__)

KYIV_LAT = 50.45
KYIV_LNG = 30.52
UPDATE_INTERVAL_S = 600


class WeatherUpdaterWorker:
    """Periodically fetches weather and pushes the global factor into Redis."""

    def __init__(self, redis: Redis) -> None:
        self._weights = GraphWeightManager(redis)
        self._weather = WeatherService()
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                conditions = await self._weather.get_current(KYIV_LAT, KYIV_LNG)
                factor = conditions.weight_factor
                await self._weights.set_global_weather_factor(
                    factor,
                    ttl_seconds=UPDATE_INTERVAL_S + 60,
                    condition=conditions.condition,
                    temperature=conditions.temperature_c,
                    source=conditions.source,
                )
                logger.info(
                    "Weather updated: %s %.1f°C → weight factor %.2f",
                    conditions.condition, conditions.temperature_c, factor,
                )
            except Exception:
                logger.exception("Weather update failed")

            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=UPDATE_INTERVAL_S,
                )
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
