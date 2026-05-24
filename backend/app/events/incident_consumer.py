import json
import logging
import math
import random

from geoalchemy2 import functions as geo_func
from sqlalchemy import select

from app.events.consumer import BaseStreamConsumer
from app.models.road_segment import RoadSegment
from app.modules.route_planning.graph_weights import GraphWeightManager

logger = logging.getLogger(__name__)

AFFECTED_RADIUS_M = 300


class IncidentAnalysisConsumer(BaseStreamConsumer):
    def __init__(self, redis, session_factory) -> None:
        super().__init__(
            redis=redis,
            session_factory=session_factory,
            stream="stream:incidents",
            group="traffic-analysis-group",
            consumer_name="traffic-analysis-1",
        )

    async def _find_nearby_segments(self, lat: float, lng: float) -> list[str]:
        async with self._session_factory() as session:
            point = geo_func.ST_SetSRID(geo_func.ST_MakePoint(lng, lat), 4326)
            adjusted = AFFECTED_RADIUS_M / max(math.cos(math.radians(lat)), 0.01)
            stmt = select(RoadSegment.id).where(
                geo_func.ST_DWithin(
                    geo_func.ST_Transform(RoadSegment.geometry, 3857),
                    geo_func.ST_Transform(point, 3857),
                    adjusted,
                )
            )
            result = await session.execute(stmt)
            return [str(row[0]) for row in result.all()]

    async def process_message(self, msg_id: str, data: dict) -> None:
        try:
            incident_id = data["incident_id"]
            lat = float(data["lat"])
            lng = float(data["lng"])
            severity = data.get("severity", "medium")
            action = data.get("action", "new")

            segment_ids = await self._find_nearby_segments(lat, lng)

            if action == "resolved":
                weights = GraphWeightManager(self._redis)
                await weights.clear_incident_zone(segment_ids)
                logger.info(
                    "Incident %s resolved — cleared %d segment weights",
                    incident_id, len(segment_ids),
                )

            predicted_delays = {
                sid: round(random.uniform(2, 15), 1)
                for sid in segment_ids
            }

            await self._redis.xadd("stream:incidents:analyzed", {
                "incident_id": incident_id,
                "severity": severity,
                "lat": str(lat),
                "lng": str(lng),
                "action": action,
                "affected_segments": json.dumps(segment_ids),
                "predicted_delays": json.dumps(predicted_delays),
                "confidence": str(round(random.uniform(0.6, 0.95), 2)),
            })
        except Exception:
            logger.exception(
                "Failed to process incident analysis for msg %s", msg_id,
            )
