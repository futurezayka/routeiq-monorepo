from datetime import datetime

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.route import Route
from app.models.telemetry import Telemetry


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_segment_speeds(
        self, time_from: datetime, time_to: datetime,
    ) -> list[dict]:
        stmt = (
            select(
                Telemetry.road_segment_id.label("segment_id"),
                func.avg(Telemetry.speed_kmh).label("avg_speed"),
                func.count().label("sample_count"),
            )
            .where(
                Telemetry.time >= time_from,
                Telemetry.time <= time_to,
                Telemetry.road_segment_id.isnot(None),
                Telemetry.speed_kmh.isnot(None),
            )
            .group_by(Telemetry.road_segment_id)
        )
        result = await self._session.execute(stmt)
        return [
            {
                "segment_id": row.segment_id,
                "avg_speed": float(row.avg_speed),
                "sample_count": row.sample_count,
            }
            for row in result
        ]

    async def get_incident_history(
        self,
        time_from: datetime,
        time_to: datetime,
        incident_type: str | None = None,
    ) -> list[Incident]:
        stmt = (
            select(Incident)
            .where(
                Incident.reported_at >= time_from,
                Incident.reported_at <= time_to,
            )
            .order_by(Incident.reported_at.desc())
        )
        if incident_type:
            stmt = stmt.where(Incident.type == incident_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_route_efficiency(
        self, time_from: datetime, time_to: datetime,
    ) -> list[dict]:
        actual = (
            func.extract("epoch", func.max(Telemetry.time) - Route.created_at)
            / 60.0
        )
        stmt = (
            select(
                Route.id.label("route_id"),
                Route.eta_minutes,
                Route.recalculation_count,
                actual.label("actual_minutes"),
            )
            .outerjoin(
                Telemetry,
                (Telemetry.vehicle_id == Route.vehicle_id)
                & (Telemetry.time >= Route.created_at)
                & (Telemetry.time <= time_to),
            )
            .where(
                Route.created_at >= time_from,
                Route.created_at <= time_to,
            )
            .group_by(Route.id, Route.eta_minutes, Route.recalculation_count, Route.created_at)
            .having(func.max(Telemetry.time).isnot(None))
        )
        result = await self._session.execute(stmt)
        return [
            {
                "route_id": row.route_id,
                "planned_eta": row.eta_minutes,
                "actual_minutes": float(row.actual_minutes) if row.actual_minutes else None,
                "recalculation_count": row.recalculation_count,
            }
            for row in result
        ]

    async def get_speed_grid(
        self, time_from: datetime, time_to: datetime,
    ) -> list[dict]:
        lat_r = func.round(cast(Telemetry.latitude, Numeric), 3)
        lng_r = func.round(cast(Telemetry.longitude, Numeric), 3)
        stmt = (
            select(
                lat_r.label("lat"),
                lng_r.label("lng"),
                func.avg(Telemetry.speed_kmh).label("avg_speed"),
            )
            .where(
                Telemetry.time >= time_from,
                Telemetry.time <= time_to,
                Telemetry.speed_kmh.isnot(None),
            )
            .group_by(lat_r, lng_r)
        )
        result = await self._session.execute(stmt)
        return [
            {
                "lat": float(row.lat),
                "lng": float(row.lng),
                "avg_speed": float(row.avg_speed),
            }
            for row in result
        ]
