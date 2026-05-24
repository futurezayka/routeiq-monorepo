import math
import uuid

from geoalchemy2 import functions as geo_func
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.incident import Incident
from app.models.road_segment import RoadSegment
from app.models.route import Route
from app.models.vehicle import Vehicle


def _m3857(lat: float, radius_m: float) -> float:
    """Compensate EPSG:3857 scale distortion at given latitude."""
    return radius_m / max(math.cos(math.radians(lat)), 0.01)


class RouteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: dict) -> Route:
        route = Route(**data)
        self._session.add(route)
        await self._session.flush()
        return route

    async def list_active(self) -> list[Route]:
        result = await self._session.execute(
            select(Route)
            .where(Route.status == "active")
            .order_by(Route.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, route_id: uuid.UUID) -> Route | None:
        result = await self._session.execute(
            select(Route).where(Route.id == route_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_vehicle(
        self, vehicle_id: uuid.UUID,
    ) -> Route | None:
        result = await self._session.execute(
            select(Route)
            .where(Route.vehicle_id == vehicle_id, Route.status == "active")
            .order_by(Route.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def cancel_active_for_vehicle(self, vehicle_id: uuid.UUID) -> int:
        result = await self._session.execute(
            update(Route)
            .where(Route.vehicle_id == vehicle_id, Route.status == "active")
            .values(status="cancelled")
        )
        await self._session.flush()
        return result.rowcount

    async def get_routes_through_area(
        self, lat: float, lng: float, radius_m: float,
    ) -> list[Route]:
        point = geo_func.ST_SetSRID(geo_func.ST_MakePoint(lng, lat), 4326)
        stmt = (
            select(Route)
            .options(joinedload(Route.vehicle))
            .where(
                Route.status == "active",
                Route.waypoints.isnot(None),
                geo_func.ST_DWithin(
                    geo_func.ST_Transform(Route.waypoints, 3857),
                    geo_func.ST_Transform(point, 3857),
                    _m3857(lat, radius_m),
                ),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.unique().scalars().all())

    async def get_rerouted_routes(self) -> list[Route]:
        stmt = (
            select(Route)
            .options(joinedload(Route.vehicle))
            .where(
                Route.status == "active",
                Route.waypoints.isnot(None),
                Route.recalculation_count > 0,
            )
        )
        result = await self._session.execute(stmt)
        return list(result.unique().scalars().all())

    async def update_route(
        self,
        route_id: uuid.UUID,
        new_waypoints,
        new_distance_km: float,
        new_eta: int,
    ) -> Route | None:
        await self._session.execute(
            update(Route)
            .where(Route.id == route_id)
            .values(
                waypoints=new_waypoints,
                distance_km=new_distance_km,
                eta_minutes=new_eta,
                recalculation_count=Route.recalculation_count + 1,
            )
        )
        await self._session.flush()
        return await self.get_by_id(route_id)

    async def get_nearby_segments(
        self, lat: float, lng: float, radius_m: float = 5000,
    ) -> list[RoadSegment]:
        point = geo_func.ST_SetSRID(geo_func.ST_MakePoint(lng, lat), 4326)
        stmt = select(RoadSegment).where(
            geo_func.ST_DWithin(
                geo_func.ST_Transform(RoadSegment.geometry, 3857),
                geo_func.ST_Transform(point, 3857),
                _m3857(lat, radius_m),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def has_active_incidents_nearby(
        self, lat: float, lng: float, radius_m: float = 5000,
    ) -> bool:
        point = geo_func.ST_SetSRID(geo_func.ST_MakePoint(lng, lat), 4326)
        stmt = (
            select(func.count())
            .select_from(Incident)
            .where(
                Incident.is_active.is_(True),
                geo_func.ST_DWithin(
                    geo_func.ST_Transform(Incident.location, 3857),
                    geo_func.ST_Transform(point, 3857),
                    _m3857(lat, radius_m),
                ),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one() > 0

    async def get_active_incidents_nearby(
        self, lat: float, lng: float, radius_m: float = 5000,
    ) -> list[Incident]:
        point = geo_func.ST_SetSRID(geo_func.ST_MakePoint(lng, lat), 4326)
        stmt = (
            select(Incident)
            .where(
                Incident.is_active.is_(True),
                geo_func.ST_DWithin(
                    geo_func.ST_Transform(Incident.location, 3857),
                    geo_func.ST_Transform(point, 3857),
                    _m3857(lat, radius_m),
                ),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_active_incidents(self) -> list[Incident]:
        stmt = select(Incident).where(Incident.is_active.is_(True))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
