import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import NullPool, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.events.telemetry_consumer import TelemetryConsumer
from app.models.telemetry import Telemetry
from app.models.vehicle import Vehicle
from app.ws.manager import ConnectionManager


def _make_consumer_factory():
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    fac = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, fac


def _unique_email() -> str:
    return f"ws_{uuid.uuid4().hex[:8]}@routeiq.io"


async def _setup_vehicle(client: AsyncClient) -> tuple[str, str]:
    """Register user, login, create vehicle. Return (vehicle_id, token)."""
    email = _unique_email()
    pw = "StrongP@ss1"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": pw,
        "full_name": "WS Driver", "role": "driver",
    })
    token = (await client.post("/api/v1/auth/login", json={
        "email": email, "password": pw,
    })).json()["access_token"]

    plate = f"WS{uuid.uuid4().hex[:4].upper()}WS"
    vehicle = (await client.post(
        "/api/v1/vehicles",
        json={"license_plate": plate, "vehicle_type": "van"},
        headers={"Authorization": f"Bearer {token}"},
    )).json()
    return vehicle["id"], token


async def test_telemetry_event_processed_by_consumer(
    client: AsyncClient, redis_client: Redis,
) -> None:
    vehicle_id, _ = await _setup_vehicle(client)
    ts = datetime.now(timezone.utc)

    await redis_client.delete("stream:telemetry")

    engine, factory = _make_consumer_factory()
    consumer = TelemetryConsumer(redis_client, factory)
    task = asyncio.create_task(consumer.run())
    try:
        await asyncio.sleep(0.3)

        await redis_client.xadd("stream:telemetry", {
            "vehicle_id": vehicle_id,
            "lat": "50.4501",
            "lng": "30.5234",
            "speed": "55.0",
            "heading": "90.0",
            "timestamp": ts.isoformat(),
        })

        await asyncio.sleep(2)

        async with factory() as session:
            row = (await session.execute(
                select(Telemetry).where(Telemetry.vehicle_id == vehicle_id)
            )).scalar_one()
            assert row.latitude == pytest.approx(50.4501)
            assert row.longitude == pytest.approx(30.5234)
            assert row.speed_kmh == pytest.approx(55.0)

            veh = (await session.execute(
                select(Vehicle).where(Vehicle.id == vehicle_id)
            )).scalar_one()
            assert veh.status == "active"
            assert veh.last_seen is not None
    finally:
        consumer.stop()
        await task
        try:
            await engine.dispose()
        except Exception:
            pass


class _MockWebSocket:
    """Minimal stand-in for starlette.websockets.WebSocket."""

    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict, mode: str = "text") -> None:
        self.messages.append(data)


async def test_telemetry_triggers_ws_notification(
    client: AsyncClient, redis_client: Redis,
) -> None:
    vehicle_id, _ = await _setup_vehicle(client)

    await redis_client.delete("stream:telemetry")

    mgr_redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    manager = ConnectionManager(mgr_redis)

    mock_ws = _MockWebSocket()
    await manager.connect(mock_ws, "positions")

    pubsub_task = asyncio.create_task(manager.run_pubsub_listener())

    engine, factory = _make_consumer_factory()
    consumer = TelemetryConsumer(redis_client, factory)
    consumer_task = asyncio.create_task(consumer.run())

    try:
        await asyncio.sleep(0.5)

        await redis_client.xadd("stream:telemetry", {
            "vehicle_id": vehicle_id,
            "lat": "50.45",
            "lng": "30.52",
            "speed": "60.0",
            "heading": "180.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await asyncio.sleep(3)

        assert len(mock_ws.messages) >= 1
        msg = mock_ws.messages[0]
        assert msg["vehicle_id"] == vehicle_id
        assert msg["lat"] == pytest.approx(50.45)
        assert msg["lng"] == pytest.approx(30.52)
        assert msg["speed"] == pytest.approx(60.0)
    finally:
        consumer.stop()
        manager.stop()
        await consumer_task
        await pubsub_task
        try:
            await engine.dispose()
        except Exception:
            pass
        try:
            await mgr_redis.aclose()
        except Exception:
            pass


async def test_consumer_acks_after_processing(
    client: AsyncClient, redis_client: Redis,
) -> None:
    vehicle_id, _ = await _setup_vehicle(client)

    await redis_client.delete("stream:telemetry")

    engine, factory = _make_consumer_factory()
    consumer = TelemetryConsumer(redis_client, factory)
    task = asyncio.create_task(consumer.run())
    try:
        await asyncio.sleep(0.3)

        await redis_client.xadd("stream:telemetry", {
            "vehicle_id": vehicle_id,
            "lat": "50.46",
            "lng": "30.53",
            "speed": "70.0",
            "heading": "0.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        await asyncio.sleep(2)

        info = await redis_client.xpending(
            "stream:telemetry", "agent-manager-group",
        )
        assert info["pending"] == 0
    finally:
        consumer.stop()
        await task
        try:
            await engine.dispose()
        except Exception:
            pass
