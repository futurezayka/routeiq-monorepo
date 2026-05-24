import json
import logging
from datetime import UTC, datetime

from geoalchemy2 import functions as geo_func
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.events.consumer import BaseStreamConsumer
from app.models.telemetry import Telemetry
from app.models.vehicle import Vehicle

logger = logging.getLogger(__name__)


class TelemetryConsumer(BaseStreamConsumer):
    def __init__(self, redis, session_factory) -> None:
        super().__init__(
            redis=redis,
            session_factory=session_factory,
            stream="stream:telemetry",
            group="agent-manager-group",
            consumer_name="agent-manager-1",
        )

    async def process_message(self, msg_id: str, data: dict) -> None:
        vehicle_id = data["vehicle_id"]
        lat = float(data["lat"])
        lng = float(data["lng"])
        speed = float(data.get("speed", 0))
        heading = float(data.get("heading", 0))
        raw_ts = data.get("timestamp")
        ts = datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(UTC)

        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    update(Vehicle)
                    .where(Vehicle.id == vehicle_id)
                    .values(
                        current_position=geo_func.ST_SetSRID(
                            geo_func.ST_MakePoint(lng, lat), 4326,
                        ),
                        last_seen=ts,
                        status="active",
                    )
                )
                session.add(Telemetry(
                    time=ts,
                    vehicle_id=vehicle_id,
                    latitude=lat,
                    longitude=lng,
                    speed_kmh=speed,
                    heading=heading,
                ))
        except IntegrityError:
            logger.warning(
                "Skipping telemetry for unknown vehicle %s (msg %s)",
                vehicle_id, msg_id,
            )
            return

        await self._redis.publish("ws:positions", json.dumps({
            "vehicle_id": vehicle_id,
            "lat": lat,
            "lng": lng,
            "speed": speed,
            "heading": heading,
        }))
