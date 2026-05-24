import uuid
from datetime import datetime

from geoalchemy2 import functions as geo_func
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle


class VehicleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: dict) -> Vehicle:
        vehicle = Vehicle(**data)
        self._session.add(vehicle)
        await self._session.flush()
        return vehicle

    async def get_by_id(self, vehicle_id: uuid.UUID) -> Vehicle | None:
        result = await self._session.execute(
            select(Vehicle).where(Vehicle.id == vehicle_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Vehicle]:
        result = await self._session.execute(select(Vehicle))
        return list(result.scalars().all())

    async def list_active(self) -> list[Vehicle]:
        result = await self._session.execute(
            select(Vehicle).where(Vehicle.status != "offline")
        )
        return list(result.scalars().all())

    async def get_simulated_ids(self) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(Vehicle.id).where(Vehicle.is_simulated.is_(True))
        )
        return list(result.scalars().all())

    async def delete_simulated(self) -> int:
        result = await self._session.execute(
            delete(Vehicle).where(Vehicle.is_simulated.is_(True))
        )
        await self._session.flush()
        return result.rowcount  # type: ignore[return-value]

    async def update_position(
        self,
        vehicle_id: uuid.UUID,
        lat: float,
        lng: float,
        last_seen: datetime,
    ) -> Vehicle | None:
        stmt = (
            update(Vehicle)
            .where(Vehicle.id == vehicle_id)
            .values(
                current_position=geo_func.ST_SetSRID(
                    geo_func.ST_MakePoint(lng, lat), 4326
                ),
                last_seen=last_seen,
                status="active",
            )
            .returning(Vehicle)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
