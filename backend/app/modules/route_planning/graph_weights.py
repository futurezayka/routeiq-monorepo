import json
import logging

from redis.asyncio import Redis

from app.modules.route_planning.incident_config import INCIDENT_TTL_S

logger = logging.getLogger(__name__)


SEVERITY_FACTORS: dict[str, float] = {
    "low":      1.5,
    "medium":   3.0,
    "high":     5.0,
    "critical": 9.0,
}
MAX_COMBINED_WEIGHT = 10.0


class GraphWeightManager:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def edge_weight(
        self,
        length_m: float,
        speed_limit_kmh: int,
        segment_id: str,
    ) -> float:
        speed_ms = max(speed_limit_kmh, 5) * 1000 / 3600
        base = length_m / speed_ms
        factor = await self.get_weight(segment_id)
        return base * factor

    async def get_weight(self, segment_id: str) -> float:
        result = await self.get_weights_batch([segment_id])
        return result.get(segment_id, 1.0)

    async def get_weights_batch(self, segment_ids: list[str]) -> dict[str, float]:
        if not segment_ids:
            return {}
        pipe = self._redis.pipeline()
        for sid in segment_ids:
            pipe.get(f"weight:{sid}:incident")
            pipe.get(f"weight:{sid}:congestion")
            pipe.get(f"weight:{sid}:weather")
        pipe.get("weight:_global:weather")
        raw = await pipe.execute()

        global_weather_raw = raw[-1]
        global_weather = 1.0
        if global_weather_raw:
            try:
                global_weather = json.loads(global_weather_raw)["factor"]
            except (json.JSONDecodeError, KeyError):
                try:
                    global_weather = float(global_weather_raw)
                except (ValueError, TypeError):
                    pass

        result: dict[str, float] = {}
        for i, sid in enumerate(segment_ids):
            base = i * 3
            try:
                incident = float(raw[base]) if raw[base] else 1.0
            except (ValueError, TypeError):
                incident = 1.0
            try:
                congestion = float(raw[base + 1]) if raw[base + 1] else 1.0
            except (ValueError, TypeError):
                congestion = 1.0
            try:
                weather = float(raw[base + 2]) if raw[base + 2] else global_weather
            except (ValueError, TypeError):
                weather = global_weather
            result[sid] = min(incident * congestion * weather, MAX_COMBINED_WEIGHT)
        return result

    async def mark_incident_zone(
        self,
        segment_ids: list[str],
        severity: str,
        ttl_seconds: int | None = None,
    ) -> None:
        factor = SEVERITY_FACTORS.get(severity, SEVERITY_FACTORS["low"])
        if ttl_seconds is None:
            ttl_seconds = INCIDENT_TTL_S.get(
                severity, INCIDENT_TTL_S["medium"],
            )
        pipe = self._redis.pipeline()
        for sid in segment_ids:
            pipe.setex(f"weight:{sid}:incident", ttl_seconds, str(factor))
        await pipe.execute()
        logger.info(
            "Marked %d segments incident-affected "
            "(factor=%.1f, severity=%s, ttl=%ds)",
            len(segment_ids), factor, severity, ttl_seconds,
        )

    async def clear_incident_zone(
        self, segment_ids: list[str],
    ) -> None:
        if not segment_ids:
            return
        pipe = self._redis.pipeline()
        for sid in segment_ids:
            pipe.delete(f"weight:{sid}:incident")
        await pipe.execute()
        logger.info("Cleared incident weights for %d segments", len(segment_ids))

    async def update_incident_factor(
        self, segment_id: str, factor: float,
    ) -> None:
        await self._redis.set(f"weight:{segment_id}:incident", str(factor))

    async def update_congestion_factor(
        self, segment_id: str, factor: float,
    ) -> None:
        await self._redis.set(f"weight:{segment_id}:congestion", str(factor))

    async def update_weather_factor(
        self, segment_id: str, factor: float, ttl_seconds: int = 3600,
    ) -> None:
        await self._redis.set(
            f"weight:{segment_id}:weather", str(factor), ex=ttl_seconds,
        )

    async def set_global_weather_factor(
        self,
        factor: float,
        ttl_seconds: int = 3600,
        condition: str = "",
        temperature: float = 0.0,
        source: str = "stub",
    ) -> None:
        payload = json.dumps({
            "factor": factor,
            "condition": condition,
            "temperature": temperature,
            "source": source,
        })
        await self._redis.set(
            "weight:_global:weather", payload, ex=ttl_seconds,
        )

    async def get_global_weather_factor(self) -> float:
        raw = await self._redis.get("weight:_global:weather")
        if not raw:
            return 1.0
        try:
            return json.loads(raw)["factor"]
        except (json.JSONDecodeError, KeyError):
            return float(raw)
