import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest
from geoalchemy2.shape import from_shape
from httpx import AsyncClient
from redis.asyncio import Redis
from shapely.geometry import LineString, Point
from geoalchemy2 import functions as geo_func
from sqlalchemy import NullPool, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.events.incident_consumer import IncidentAnalysisConsumer
from app.events.route_update_consumer import RouteUpdateConsumer
from app.models.incident import Incident
from app.models.road_segment import RoadSegment
from app.models.route import Route
from app.models.user import User
from app.models.vehicle import Vehicle
from app.ws.manager import ConnectionManager


def _make_factory():
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    fac = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, fac


def _unique_email() -> str:
    return f"inc_{uuid.uuid4().hex[:8]}@routeiq.io"


async def _auth_token(client: AsyncClient) -> tuple[str, str]:
    email = _unique_email()
    pw = "StrongP@ss1"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email, "password": pw,
        "full_name": "Incident Tester", "role": "dispatcher",
    })
    user_id = reg.json()["id"]
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": pw,
    })
    return login.json()["access_token"], user_id


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Incident coords: Kyiv centre (50.45, 30.52) ──
INC_LAT, INC_LNG = 50.45, 30.52


async def _seed_segment_and_route(factory):
    """Create a road segment and a route through the incident area."""
    async with factory() as s:
        async with s.begin():
            center = geo_func.ST_SetSRID(
                geo_func.ST_MakePoint(INC_LNG, INC_LAT), 4326,
            )
            await s.execute(
                delete(Route).where(
                    Route.status == "active",
                    Route.waypoints.isnot(None),
                    geo_func.ST_DWithin(
                        geo_func.ST_Transform(Route.waypoints, 3857),
                        geo_func.ST_Transform(center, 3857),
                        5000,
                    ),
                )
            )
            await s.execute(
                delete(RoadSegment).where(
                    geo_func.ST_DWithin(
                        geo_func.ST_Transform(RoadSegment.geometry, 3857),
                        geo_func.ST_Transform(center, 3857),
                        5000,
                    )
                )
            )

            user = User(
                email=_unique_email(),
                password_hash="x",
                role="driver",
                full_name="Seed Driver",
            )
            s.add(user)
            await s.flush()

            vehicle = Vehicle(
                driver_id=user.id,
                license_plate=f"SD{uuid.uuid4().hex[:4].upper()}SD",
                vehicle_type="van",
            )
            s.add(vehicle)
            await s.flush()

            seg = RoadSegment(
                osm_way_id=int(uuid.uuid4().int % 10**9),
                geometry=from_shape(
                    LineString([(INC_LNG - 0.001, INC_LAT),
                                (INC_LNG + 0.001, INC_LAT)]),
                    srid=4326,
                ),
                name="Test Segment",
                road_type="primary",
                speed_limit=50,
                length_m=200,
                lanes=2,
            )
            s.add(seg)
            await s.flush()

            route = Route(
                vehicle_id=vehicle.id,
                status="active",
                origin=from_shape(Point(INC_LNG - 0.01, INC_LAT), srid=4326),
                destination=from_shape(Point(INC_LNG + 0.01, INC_LAT), srid=4326),
                waypoints=from_shape(
                    LineString([(INC_LNG - 0.01, INC_LAT),
                                (INC_LNG, INC_LAT),
                                (INC_LNG + 0.01, INC_LAT)]),
                    srid=4326,
                ),
                distance_km=2.0,
                eta_minutes=5,
            )
            s.add(route)
            await s.flush()

            return str(seg.id), str(route.id)


# ──────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────


async def test_report_incident_returns_201(client: AsyncClient) -> None:
    token, user_id = await _auth_token(client)

    resp = await client.post(
        "/api/v1/incidents",
        json={
            "type": "accident",
            "severity": "high",
            "latitude": INC_LAT,
            "longitude": INC_LNG,
        },
        headers=_hdr(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "accident"
    assert body["severity"] == "high"
    assert body["latitude"] == pytest.approx(INC_LAT)
    assert body["longitude"] == pytest.approx(INC_LNG)
    assert body["is_active"] is True
    assert body["reported_by"] == user_id


async def test_report_incident_publishes_to_stream(
    client: AsyncClient, redis_client: Redis,
) -> None:
    token, _ = await _auth_token(client)

    await redis_client.delete("stream:incidents")

    resp = await client.post(
        "/api/v1/incidents",
        json={
            "type": "congestion",
            "severity": "medium",
            "latitude": INC_LAT,
            "longitude": INC_LNG,
        },
        headers=_hdr(token),
    )
    incident_id = resp.json()["id"]

    messages = await redis_client.xrevrange("stream:incidents", count=5)
    found = False
    for _mid, fields in messages:
        if fields.get("incident_id") == incident_id:
            assert fields["type"] == "congestion"
            assert fields["severity"] == "medium"
            found = True
            break
    assert found, "Incident event not found in stream:incidents"


async def test_incident_consumer_finds_affected_segments(
    client: AsyncClient, redis_client: Redis,
) -> None:
    engine, factory = _make_factory()
    seg_id, _ = await _seed_segment_and_route(factory)

    await redis_client.delete("stream:incidents")
    await redis_client.delete("stream:incidents:analyzed")

    consumer = IncidentAnalysisConsumer(redis_client, factory)
    task = asyncio.create_task(consumer.run())
    try:
        await asyncio.sleep(0.3)

        await redis_client.xadd("stream:incidents", {
            "incident_id": str(uuid.uuid4()),
            "type": "accident",
            "severity": "high",
            "lat": str(INC_LAT),
            "lng": str(INC_LNG),
        })

        await asyncio.sleep(2)

        messages = await redis_client.xrevrange(
            "stream:incidents:analyzed", count=5,
        )
        assert len(messages) >= 1
        _, fields = messages[0]
        segments = json.loads(fields["affected_segments"])
        assert seg_id in segments
        assert float(fields["confidence"]) > 0
    finally:
        consumer.stop()
        await task
        try:
            await engine.dispose()
        except Exception:
            pass


async def test_incident_triggers_route_update_event(
    client: AsyncClient, redis_client: Redis,
) -> None:
    engine, factory = _make_factory()
    seg_id, route_id = await _seed_segment_and_route(factory)

    await redis_client.delete("stream:incidents:analyzed")
    await redis_client.delete("stream:route-updates")

    consumer = RouteUpdateConsumer(redis_client, factory)
    task = asyncio.create_task(consumer.run())
    try:
        await asyncio.sleep(0.3)

        await redis_client.xadd("stream:incidents:analyzed", {
            "incident_id": str(uuid.uuid4()),
            "severity": "high",
            "lat": str(INC_LAT),
            "lng": str(INC_LNG),
            "affected_segments": json.dumps([seg_id]),
            "predicted_delays": json.dumps({seg_id: 8.5}),
            "confidence": "0.85",
        })

        await asyncio.sleep(2)

        messages = await redis_client.xrevrange(
            "stream:route-updates", count=20,
        )
        assert len(messages) >= 1
        route_ids = [f["route_id"] for _, f in messages]
        assert route_id in route_ids
        matching = [f for _, f in messages if f["route_id"] == route_id]
        assert matching[0]["reason"] == "incident_reroute"

        async with factory() as session:
            route = (await session.execute(
                select(Route).where(Route.id == route_id)
            )).scalar_one()
            assert route.recalculation_count >= 1
    finally:
        consumer.stop()
        await task
        try:
            await engine.dispose()
        except Exception:
            pass


class _MockWS:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict, mode: str = "text") -> None:
        self.messages.append(data)


async def test_incident_notification_sent_to_ws(
    client: AsyncClient, redis_client: Redis,
) -> None:
    engine, factory = _make_factory()
    await _seed_segment_and_route(factory)

    await redis_client.delete("stream:incidents:analyzed")

    mgr_redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    manager = ConnectionManager(mgr_redis)

    mock_ws = _MockWS()
    await manager.connect(mock_ws, "incidents")

    pubsub_task = asyncio.create_task(manager.run_pubsub_listener())

    consumer = RouteUpdateConsumer(redis_client, factory)
    consumer_task = asyncio.create_task(consumer.run())

    try:
        await asyncio.sleep(0.5)

        await redis_client.xadd("stream:incidents:analyzed", {
            "incident_id": str(uuid.uuid4()),
            "severity": "high",
            "lat": str(INC_LAT),
            "lng": str(INC_LNG),
            "affected_segments": json.dumps([]),
            "predicted_delays": json.dumps({}),
            "confidence": "0.80",
        })

        await asyncio.sleep(3)

        assert len(mock_ws.messages) >= 1
        msg = mock_ws.messages[0]
        assert msg["lat"] == pytest.approx(INC_LAT)
        assert msg["lng"] == pytest.approx(INC_LNG)
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
