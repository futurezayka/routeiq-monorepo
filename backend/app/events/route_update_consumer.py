import json
import logging

from app.events.consumer import BaseStreamConsumer
from app.events.publisher import EventBus
from app.modules.route_planning.graph_weights import GraphWeightManager
from app.modules.route_planning.osrm_client import OSRMClient
from app.modules.route_planning.repository import RouteRepository
from app.modules.route_planning.service import RoutePlanningService

logger = logging.getLogger(__name__)


class RouteUpdateConsumer(BaseStreamConsumer):
    def __init__(self, redis, session_factory) -> None:
        super().__init__(
            redis=redis,
            session_factory=session_factory,
            stream="stream:incidents:analyzed",
            group="route-planning-group",
            consumer_name="route-planning-1",
        )

    async def process_message(self, msg_id: str, data: dict) -> None:
        try:
            incident_id = data["incident_id"]
            lat = float(data["lat"])
            lng = float(data["lng"])
            severity = data.get("severity", "medium")
            action = data.get("action", "new")
            affected_segments = json.loads(data.get("affected_segments", "[]"))

            logger.info(
                "Rerouting for incident %s at (%.5f, %.5f), severity=%s, action=%s, affected_segments=%d",
                incident_id, lat, lng, severity, action, len(affected_segments),
            )

            async with self._session_factory() as session, session.begin():
                service = RoutePlanningService(
                    repo=RouteRepository(session),
                    osrm=OSRMClient(),
                    weights=GraphWeightManager(self._redis),
                    event_bus=EventBus(self._redis),
                    redis=self._redis,
                )
                results = await service.reroute_affected(
                    incident_id, affected_segments, lat, lng,
                    severity=severity, action=action,
                )
                logger.info(
                    "Reroute complete: incident=%s, routes_updated=%d",
                    incident_id, len(results),
                )
        except Exception:
            logger.exception(
                "Failed to process route update for msg %s", msg_id,
            )
