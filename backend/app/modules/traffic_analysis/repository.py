import math
import uuid
from datetime import UTC, datetime, timedelta

from geoalchemy2 import functions as geo_func
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: dict) -> Incident:
        incident = Incident(**data)
        self._session.add(incident)
        await self._session.flush()
        return incident

    async def get_by_id(self, incident_id: uuid.UUID) -> Incident | None:
        result = await self._session.execute(
            select(Incident).where(Incident.id == incident_id)
        )
        return result.scalar_one_or_none()

    async def get_active(
        self,
        incident_type: str | None = None,
    ) -> list[Incident]:
        stmt = select(Incident).where(Incident.is_active.is_(True))
        if incident_type:
            stmt = stmt.where(Incident.type == incident_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_in_radius(
        self, lat: float, lng: float, radius_m: float,
    ) -> list[Incident]:
        point = geo_func.ST_SetSRID(geo_func.ST_MakePoint(lng, lat), 4326)
        adjusted = radius_m / max(math.cos(math.radians(lat)), 0.01)
        stmt = (
            select(Incident)
            .where(Incident.is_active.is_(True))
            .where(
                geo_func.ST_DWithin(
                    geo_func.ST_Transform(Incident.location, 3857),
                    geo_func.ST_Transform(point, 3857),
                    adjusted,
                )
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate(self, incident_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Incident)
            .where(Incident.id == incident_id)
            .values(
                is_active=False,
                resolved_at=datetime.now(UTC),
            )
        )
        await self._session.flush()

    async def resolve_stale(self, max_age_hours: int = 1) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        result = await self._session.execute(
            update(Incident)
            .where(
                Incident.is_active.is_(True),
                Incident.reported_at < cutoff,
            )
            .values(is_active=False, resolved_at=datetime.now(UTC))
        )
        await self._session.flush()
        return result.rowcount  # type: ignore[return-value]

    async def delete_simulated(self) -> int:
        result = await self._session.execute(
            delete(Incident).where(Incident.is_simulated.is_(True))
        )
        await self._session.flush()
        return result.rowcount  # type: ignore[return-value]
