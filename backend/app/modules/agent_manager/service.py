import json
import logging
import uuid
from datetime import UTC, datetime

from geoalchemy2.shape import to_shape
from redis.asyncio import Redis

from app.core.exceptions import ForbiddenError, NotFoundError
from app.events.publisher import EventBus
from app.modules.agent_manager.repository import VehicleRepository
from app.schemas.telemetry import TelemetryCreate
from app.schemas.vehicle import VehicleCreate, VehicleResponse

logger = logging.getLogger(__name__)


class AgentManagerService:
    def __init__(
        self,
        repo: VehicleRepository,
        redis: Redis,
        event_bus: EventBus,
    ) -> None:
        self._repo = repo
        self._redis = redis
        self._event_bus = event_bus

    @staticmethod
    def _to_response(vehicle) -> VehicleResponse:
        pos = None
        if vehicle.current_position is not None:
            pt = to_shape(vehicle.current_position)
            pos = {"type": "Point", "coordinates": [pt.x, pt.y]}
        return VehicleResponse(
            id=vehicle.id,
            driver_id=vehicle.driver_id,
            license_plate=vehicle.license_plate,
            vehicle_type=vehicle.vehicle_type,
            status=vehicle.status,
            is_simulated=vehicle.is_simulated,
            last_seen=vehicle.last_seen,
            current_position=pos,
        )

    async def register_vehicle(
        self, data: VehicleCreate, driver_id: str
    ) -> VehicleResponse:
        vehicle = await self._repo.create({
            "driver_id": driver_id,
            "license_plate": data.license_plate,
            "vehicle_type": data.vehicle_type,
            "is_simulated": data.is_simulated,
        })
        return self._to_response(vehicle)

    async def list_vehicles(self) -> list[VehicleResponse]:
        vehicles = await self._repo.list_all()
        return [self._to_response(v) for v in vehicles]

    async def get_vehicle(self, vehicle_id: str) -> VehicleResponse:
        vehicle = await self._repo.get_by_id(vehicle_id)
        if not vehicle:
            raise NotFoundError("Vehicle not found")
        return self._to_response(vehicle)

    async def ingest_telemetry(
        self,
        data: TelemetryCreate,
        driver_id: uuid.UUID | None = None,
    ) -> None:
        """Ingest telemetry. If driver_id is given (driver role), enforce ownership."""
        if driver_id is not None:
            vehicle = await self._repo.get_by_id(data.vehicle_id)
            if vehicle is None:
                raise NotFoundError("Vehicle not found")
            if vehicle.driver_id != driver_id:
                raise ForbiddenError("Cannot post telemetry for another driver's vehicle")

        now = datetime.now(UTC)

        await self._repo.update_position(
            data.vehicle_id, data.latitude, data.longitude, now,
        )

        cache_payload = json.dumps({
            "lat": data.latitude,
            "lng": data.longitude,
            "speed": data.speed_kmh,
            "heading": data.heading,
            "ts": now.isoformat(),
        })
        try:
            await self._redis.set(
                f"vehicle:{data.vehicle_id}:pos", cache_payload, ex=30,
            )
        except Exception:
            logger.warning("Redis unavailable — skipping position cache")

        try:
            await self._event_bus.publish("stream:telemetry", {
                "vehicle_id": str(data.vehicle_id),
                "lat": str(data.latitude),
                "lng": str(data.longitude),
                "speed": str(data.speed_kmh or 0),
                "heading": str(data.heading or 0),
                "timestamp": now.isoformat(),
            })
        except Exception:
            logger.warning("Redis unavailable — skipping telemetry stream")
