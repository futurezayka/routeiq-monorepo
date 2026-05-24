"""
Full end-to-end test: Incident → Reroute pipeline.

Sequence tested (from UML Sequence Diagram):
  Register users → Create vehicles → Plan routes → Telemetry flow
  → Report incident → Incident analysis → Route recalculation
  → WebSocket notifications
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

import pytest
from geoalchemy2.shape import from_shape
from httpx import AsyncClient
from redis.asyncio import Redis
from shapely.geometry import LineString, Point
from sqlalchemy import NullPool, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.events.incident_consumer import IncidentAnalysisConsumer
from app.events.route_update_consumer import RouteUpdateConsumer
from app.events.telemetry_consumer import TelemetryConsumer
from app.models.incident import Incident
from app.models.road_segment import RoadSegment
from app.models.route import Route
from app.ws.manager import ConnectionManager


KYIV_CENTER_LAT = 50.4500
KYIV_CENTER_LNG = 30.5200


def _make_factory():
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    fac = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, fac


def _unique_email() -> str:
    return f"e2e_{uuid.uuid4().hex[:8]}@routeiq.io"


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register_login(client: AsyncClient, role: str) -> tuple[str, str]:
    email = _unique_email()
    pwd = "E2eP@ssw0rd"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email, "password": pwd,
        "full_name": f"E2E {role.title()}", "role": role,
    })
    assert reg.status_code == 201, f"Register failed: {reg.text}"
    user_id = reg.json()["id"]
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": pwd,
    })
    assert login.status_code == 200, f"Login failed: {login.text}"
    return login.json()["access_token"], user_id


class _MockWS:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict, mode: str = "text") -> None:
        self.messages.append(data)


async def test_full_incident_reroute_scenario(
    client: AsyncClient, redis_client: Redis,
) -> None:
    engine, factory = _make_factory()
    scenario_start = time.monotonic()

    try:
        # ── Step 1: Register dispatcher + 3 drivers ──
        disp_token, disp_id = await _register_login(client, "dispatcher")
        drivers = []
        for _ in range(3):
            token, uid = await _register_login(client, "driver")
            drivers.append((token, uid))

        # ── Step 2: Create road segment near incident area ──
        async with factory() as s:
            async with s.begin():
                seg = RoadSegment(
                    osm_way_id=int(uuid.uuid4().int % 10**9),
                    geometry=from_shape(
                        LineString([
                            (KYIV_CENTER_LNG - 0.005, KYIV_CENTER_LAT),
                            (KYIV_CENTER_LNG + 0.005, KYIV_CENTER_LAT),
                        ]),
                        srid=4326,
                    ),
                    name="E2E Test Segment",
                    road_type="primary",
                    speed_limit=50,
                    length_m=800,
                    lanes=2,
                )
                s.add(seg)
                await s.flush()
                segment_id = str(seg.id)

        # ── Step 3: Create 3 vehicles ──
        vehicle_ids = []
        for i, (drv_token, _drv_id) in enumerate(drivers):
            resp = await client.post(
                "/api/v1/vehicles",
                json={
                    "license_plate": f"E2E{uuid.uuid4().hex[:4].upper()}{i:02d}",
                    "vehicle_type": "van",
                },
                headers=_hdr(drv_token),
            )
            assert resp.status_code == 201, f"Vehicle {i} create failed: {resp.text}"
            vehicle_ids.append(resp.json()["id"])

        # ── Step 4: Plan routes for each vehicle (through incident area) ──
        route_ids = []
        offsets = [
            (-0.01, 0.0, 0.01, 0.0),
            (-0.008, 0.002, 0.008, -0.002),
            (-0.009, -0.001, 0.009, 0.001),
        ]
        for i, vid in enumerate(vehicle_ids):
            o_lng, o_lat, d_lng, d_lat = offsets[i]
            resp = await client.post(
                "/api/v1/routes",
                json={
                    "vehicle_id": vid,
                    "origin_lat": KYIV_CENTER_LAT + o_lat,
                    "origin_lng": KYIV_CENTER_LNG + o_lng,
                    "destination_lat": KYIV_CENTER_LAT + d_lat,
                    "destination_lng": KYIV_CENTER_LNG + d_lng,
                },
                headers=_hdr(disp_token),
            )
            assert resp.status_code == 201, f"Route {i} plan failed: {resp.text}"
            route_ids.append(resp.json()["id"])

        # ── Step 5: Telemetry flow — 10 positions per vehicle ──
        for i, vid in enumerate(vehicle_ids):
            o_lng_off, o_lat_off, d_lng_off, d_lat_off = offsets[i]
            for step in range(10):
                frac = step / 9
                lat = KYIV_CENTER_LAT + o_lat_off + (d_lat_off - o_lat_off) * frac
                lng = KYIV_CENTER_LNG + o_lng_off + (d_lng_off - o_lng_off) * frac
                resp = await client.post("/api/v1/telemetry", json={
                    "vehicle_id": vid,
                    "latitude": lat,
                    "longitude": lng,
                    "speed_kmh": 40.0 + step,
                    "heading": 90.0,
                }, headers=_hdr(disp_token))
                assert resp.status_code == 202

        # Verify telemetry cached in Redis
        for vid in vehicle_ids:
            cached = await redis_client.get(f"vehicle:{vid}:pos")
            assert cached is not None, f"Vehicle {vid} position not cached"
            pos = json.loads(cached)
            assert "lat" in pos and "lng" in pos

        # ── Step 6: Clear streams, start consumers + WS manager ──
        for stream in ["stream:incidents", "stream:incidents:analyzed", "stream:route-updates"]:
            await redis_client.delete(stream)

        telemetry_consumer = TelemetryConsumer(redis_client, factory)
        incident_consumer = IncidentAnalysisConsumer(redis_client, factory)
        route_consumer = RouteUpdateConsumer(redis_client, factory)

        ws_redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        ws_manager = ConnectionManager(ws_redis)

        mock_incidents_ws = _MockWS()
        mock_routes_ws = _MockWS()
        await ws_manager.connect(mock_incidents_ws, "incidents")
        await ws_manager.connect(mock_routes_ws, "route-updates")

        consumer_tasks = [
            asyncio.create_task(telemetry_consumer.run()),
            asyncio.create_task(incident_consumer.run()),
            asyncio.create_task(route_consumer.run()),
        ]
        pubsub_task = asyncio.create_task(ws_manager.run_pubsub_listener())

        await asyncio.sleep(0.5)

        # ── Step 7: Report incident on route of vehicle 1 ──
        incident_time = time.monotonic()
        inc_resp = await client.post(
            "/api/v1/incidents",
            json={
                "type": "accident",
                "severity": "high",
                "latitude": KYIV_CENTER_LAT,
                "longitude": KYIV_CENTER_LNG,
            },
            headers=_hdr(disp_token),
        )
        assert inc_resp.status_code == 201
        incident_id = inc_resp.json()["id"]

        # ── Step 8: Wait for pipeline to process ──
        # Incident → IncidentAnalysis → RouteUpdate pipeline
        deadline = time.monotonic() + 10.0
        route_updates_found = False
        while time.monotonic() < deadline:
            messages = await redis_client.xrevrange("stream:route-updates", count=50)
            if messages:
                route_updates_found = True
                break
            await asyncio.sleep(0.3)

        pipeline_latency = time.monotonic() - incident_time

        # ── Verification 1: Incident created in DB ──
        async with factory() as s:
            result = await s.execute(
                select(Incident).where(Incident.id == incident_id)
            )
            db_incident = result.scalar_one_or_none()
            assert db_incident is not None, "Incident not found in DB"
            assert db_incident.type == "accident"
            assert db_incident.severity == "high"
            assert db_incident.is_active is True

        # ── Verification 2: Affected routes found ──
        analyzed = await redis_client.xrevrange("stream:incidents:analyzed", count=10)
        assert len(analyzed) >= 1, "No analyzed incidents in stream"
        _, analyzed_data = analyzed[0]
        affected_segments = json.loads(analyzed_data.get("affected_segments", "[]"))
        assert segment_id in affected_segments, (
            f"Segment {segment_id} not in affected: {affected_segments}"
        )

        # ── Verification 3: Routes recalculated ──
        assert route_updates_found, "No route updates received within timeout"
        messages = await redis_client.xrevrange("stream:route-updates", count=50)
        updated_route_ids = {f["route_id"] for _, f in messages}

        async with factory() as s:
            recalculated_count = 0
            for rid in route_ids:
                result = await s.execute(
                    select(Route).where(Route.id == rid)
                )
                route = result.scalar_one_or_none()
                if route and route.recalculation_count > 0:
                    recalculated_count += 1

        assert recalculated_count >= 1, (
            f"Expected at least 1 recalculated route, got {recalculated_count}"
        )

        # ── Verification 4: WebSocket notifications ──
        await asyncio.sleep(2)

        assert len(mock_incidents_ws.messages) >= 1, (
            f"No WS incident notifications, got {mock_incidents_ws.messages}"
        )
        inc_ws = mock_incidents_ws.messages[0]
        assert inc_ws["lat"] == pytest.approx(KYIV_CENTER_LAT)
        assert inc_ws["lng"] == pytest.approx(KYIV_CENTER_LNG)

        assert len(mock_routes_ws.messages) >= 1, (
            f"No WS route-update notifications, got {mock_routes_ws.messages}"
        )

        # ── Verification 5: End-to-end latency < 10 seconds ──
        assert pipeline_latency < 10.0, (
            f"Pipeline latency {pipeline_latency:.2f}s exceeds 10s NFR target"
        )

        total_elapsed = time.monotonic() - scenario_start
        assert total_elapsed < 30.0, (
            f"Full scenario took {total_elapsed:.2f}s (sanity bound)"
        )

    finally:
        telemetry_consumer.stop()
        incident_consumer.stop()
        route_consumer.stop()
        ws_manager.stop()
        for t in consumer_tasks:
            await t
        await pubsub_task
        try:
            await ws_redis.aclose()
        except Exception:
            pass
        try:
            await engine.dispose()
        except Exception:
            pass
