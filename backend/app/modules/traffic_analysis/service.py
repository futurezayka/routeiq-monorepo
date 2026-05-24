import logging
import uuid

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point

from app.core.exceptions import NotFoundError
from app.events.publisher import EventBus
from app.modules.traffic_analysis.repository import IncidentRepository
from app.schemas.incident import IncidentCreate, IncidentResponse

logger = logging.getLogger(__name__)


class IncidentService:
    def __init__(self, repo: IncidentRepository, event_bus: EventBus) -> None:
        self._repo = repo
        self._event_bus = event_bus

    def _to_response(self, incident) -> IncidentResponse:
        pt = to_shape(incident.location)
        return IncidentResponse(
            id=incident.id,
            reported_by=incident.reported_by,
            type=incident.type,
            severity=incident.severity,
            latitude=pt.y,
            longitude=pt.x,
            is_active=incident.is_active,
            is_simulated=incident.is_simulated,
            reported_at=incident.reported_at,
            resolved_at=incident.resolved_at,
        )

    async def report_incident(
        self, data: IncidentCreate, user_id: uuid.UUID,
    ) -> IncidentResponse:
        incident = await self._repo.create({
            "reported_by": user_id,
            "type": data.type,
            "severity": data.severity,
            "location": from_shape(
                Point(data.longitude, data.latitude), srid=4326,
            ),
            "is_simulated": data.is_simulated,
        })

        try:
            await self._event_bus.publish("stream:incidents", {
                "incident_id": str(incident.id),
                "type": data.type,
                "severity": data.severity,
                "lat": str(data.latitude),
                "lng": str(data.longitude),
            })
        except Exception:
            logger.warning("Redis unavailable — skipping incident stream")

        return self._to_response(incident)

    async def list_incidents(
        self, incident_type: str | None = None,
    ) -> list[IncidentResponse]:
        incidents = await self._repo.get_active(incident_type)
        return [self._to_response(i) for i in incidents]

    async def resolve_incident(self, incident_id: uuid.UUID) -> IncidentResponse:
        incident = await self._repo.get_by_id(incident_id)
        if not incident:
            raise NotFoundError("Incident not found")

        if not incident.is_active:
            return self._to_response(incident)

        await self._repo.deactivate(incident_id)

        pt = to_shape(incident.location)
        try:
            await self._event_bus.publish("stream:incidents", {
                "incident_id": str(incident_id),
                "type": incident.type,
                "severity": incident.severity,
                "lat": str(pt.y),
                "lng": str(pt.x),
                "action": "resolved",
            })
        except Exception:
            logger.warning("Redis unavailable — skipping resolve event")

        incident = await self._repo.get_by_id(incident_id)
        return self._to_response(incident)

    async def resolve_stale(self, max_age_hours: int = 1) -> int:
        return await self._repo.resolve_stale(max_age_hours)
