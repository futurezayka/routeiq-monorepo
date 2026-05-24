import uuid

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.route import Route
from app.models.telemetry import Telemetry
from app.models.user import User
from app.models.vehicle import Vehicle

# Major (visible, navigable) road classes used as the default filter for
# random-point sampling. Excludes residential/service so simulated incidents
# don't land in private driveways or back alleys.
DEFAULT_MAJOR_ROAD_CATEGORIES: tuple[str, ...] = (
    "motorway", "trunk", "primary", "secondary", "tertiary",
)


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_users(self) -> list[User]:
        result = await self._session.execute(
            select(User).order_by(User.created_at)
        )
        return list(result.scalars().all())

    async def list_users_paginated(
        self,
        offset: int = 0,
        limit: int = 20,
        role: str | None = None,
        search: str | None = None,
    ) -> tuple[list[User], int]:
        stmt = select(User)
        count_stmt = select(func.count()).select_from(User)

        if role:
            stmt = stmt.where(User.role == role)
            count_stmt = count_stmt.where(User.role == role)
        if search:
            pattern = f"%{search}%"
            flt = User.email.ilike(pattern) | User.full_name.ilike(pattern)
            stmt = stmt.where(flt)
            count_stmt = count_stmt.where(flt)

        total = (await self._session.execute(count_stmt)).scalar_one()
        result = await self._session.execute(
            stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def create_user(self, data: dict) -> User:
        user = User(**data)
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_simulated_vehicle_ids(self) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(Vehicle.id).where(Vehicle.is_simulated.is_(True))
        )
        return list(result.scalars().all())

    async def delete_routes_for_vehicles(
        self, vehicle_ids: list[uuid.UUID],
    ) -> int:
        if not vehicle_ids:
            return 0
        result = await self._session.execute(
            delete(Route).where(Route.vehicle_id.in_(vehicle_ids))
        )
        await self._session.flush()
        return result.rowcount or 0

    async def delete_telemetry_for_vehicles(
        self, vehicle_ids: list[uuid.UUID],
    ) -> int:
        if not vehicle_ids:
            return 0
        result = await self._session.execute(
            delete(Telemetry).where(Telemetry.vehicle_id.in_(vehicle_ids))
        )
        await self._session.flush()
        return result.rowcount or 0

    async def delete_simulated_incidents(self) -> int:
        result = await self._session.execute(
            delete(Incident).where(Incident.is_simulated.is_(True))
        )
        await self._session.flush()
        return result.rowcount or 0

    async def delete_simulated_vehicles(self) -> int:
        result = await self._session.execute(
            delete(Vehicle).where(Vehicle.is_simulated.is_(True))
        )
        await self._session.flush()
        return result.rowcount or 0

    async def random_road_points(
        self,
        n: int = 1,
        categories: tuple[str, ...] = DEFAULT_MAJOR_ROAD_CATEGORIES,
    ) -> list[tuple[float, float]]:
        """Random points lying ON LineStrings of the given road classes.

        Uses a filtered full scan + ORDER BY random() top-N heapsort
        (~20 ms on 31k rows / 8k major-road rows). We deliberately AVOID
        TABLESAMPLE here: it filters AFTER sampling, so on rare runs a 2%
        sample may contain zero major roads, silently fall back to ANY
        road, and emit incidents on residential streets — which was the
        original bug. Only when the category filter itself yields zero
        rows (e.g. unknown category list) do we widen to any road.
        """
        primary_sql = text("""
            SELECT
                ST_Y(ST_LineInterpolatePoint(geometry, random())) AS lat,
                ST_X(ST_LineInterpolatePoint(geometry, random())) AS lng
            FROM road_segments
            WHERE road_type = ANY(:cats)
            ORDER BY random()
            LIMIT :n
        """)
        result = await self._session.execute(
            primary_sql, {"cats": list(categories), "n": n},
        )
        rows = result.fetchall()
        if not rows:
            fallback_sql = text("""
                SELECT
                    ST_Y(ST_LineInterpolatePoint(geometry, random())) AS lat,
                    ST_X(ST_LineInterpolatePoint(geometry, random())) AS lng
                FROM road_segments
                ORDER BY random()
                LIMIT :n
            """)
            result = await self._session.execute(fallback_sql, {"n": n})
            rows = result.fetchall()
        return [(float(r.lat), float(r.lng)) for r in rows]
