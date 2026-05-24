import asyncio
import json
import uuid

import pytest
from geoalchemy2 import functions as geo_func
from geoalchemy2.shape import from_shape, to_shape
from httpx import AsyncClient
from redis.asyncio import Redis
from shapely.geometry import LineString, Point
from sqlalchemy import NullPool, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.events.publisher import EventBus
from app.models.road_segment import RoadSegment
from app.models.route import Route
from app.models.user import User
from app.models.vehicle import Vehicle
from app.modules.route_planning.graph_weights import GraphWeightManager
from app.modules.route_planning.osrm_client import OSRMClient
from app.modules.route_planning.repository import RouteRepository
from app.modules.route_planning.service import RoutePlanningService

# ── Coords for a 4-segment diamond network ──────────────
# Uses Vinnytsia area to avoid collision with incident tests at (50.45, 30.52)
#
#   A(49.00, 28.00) ─seg1─ B(49.00, 28.02) ─seg2─ C(49.00, 28.04)
#     \                                              /
#      seg3 ── D(48.99, 28.02) ──── seg4 ──────────
#
A_LAT, A_LNG = 49.00, 28.00
B_LAT, B_LNG = 49.00, 28.02
C_LAT, C_LNG = 49.00, 28.04
D_LAT, D_LNG = 48.99, 28.02


def _make_factory():
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    fac = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, fac


def _unique_email() -> str:
    return f"route_{uuid.uuid4().hex[:8]}@routeiq.io"


async def _seed_network(factory):
    """Create 4 segments forming two paths A→C plus a vehicle with an active route."""
    async with factory() as s:
        async with s.begin():
            center = geo_func.ST_SetSRID(geo_func.ST_MakePoint(B_LNG, B_LAT), 4326)
            await s.execute(
                delete(RoadSegment).where(
                    geo_func.ST_DWithin(
                        geo_func.ST_Transform(RoadSegment.geometry, 3857),
                        geo_func.ST_Transform(center, 3857),
                        10000,
                    )
                )
            )
            user = User(
                email=_unique_email(),
                password_hash="x",
                role="driver",
                full_name="Route Driver",
            )
            s.add(user)
            await s.flush()

            vehicle = Vehicle(
                driver_id=user.id,
                license_plate=f"RT{uuid.uuid4().hex[:4].upper()}RT",
                vehicle_type="van",
            )
            s.add(vehicle)
            await s.flush()

            seg1 = RoadSegment(
                osm_way_id=int(uuid.uuid4().int % 10**9),
                geometry=from_shape(
                    LineString([(A_LNG, A_LAT), (B_LNG, B_LAT)]), srid=4326,
                ),
                name="Seg1-direct",
                road_type="primary",
                speed_limit=50,
                length_m=200,
                lanes=2,
            )
            seg2 = RoadSegment(
                osm_way_id=int(uuid.uuid4().int % 10**9),
                geometry=from_shape(
                    LineString([(B_LNG, B_LAT), (C_LNG, C_LAT)]), srid=4326,
                ),
                name="Seg2-direct",
                road_type="primary",
                speed_limit=50,
                length_m=200,
                lanes=2,
            )
            seg3 = RoadSegment(
                osm_way_id=int(uuid.uuid4().int % 10**9),
                geometry=from_shape(
                    LineString([(A_LNG, A_LAT), (D_LNG, D_LAT)]), srid=4326,
                ),
                name="Seg3-detour",
                road_type="secondary",
                speed_limit=40,
                length_m=250,
                lanes=2,
            )
            seg4 = RoadSegment(
                osm_way_id=int(uuid.uuid4().int % 10**9),
                geometry=from_shape(
                    LineString([(D_LNG, D_LAT), (C_LNG, C_LAT)]), srid=4326,
                ),
                name="Seg4-detour",
                road_type="secondary",
                speed_limit=40,
                length_m=250,
                lanes=2,
            )
            s.add_all([seg1, seg2, seg3, seg4])
            await s.flush()

            route = Route(
                vehicle_id=vehicle.id,
                status="active",
                origin=from_shape(Point(A_LNG, A_LAT), srid=4326),
                destination=from_shape(Point(C_LNG, C_LAT), srid=4326),
                waypoints=from_shape(
                    LineString([(A_LNG, A_LAT), (B_LNG, B_LAT), (C_LNG, C_LAT)]),
                    srid=4326,
                ),
                distance_km=0.4,
                eta_minutes=1,
            )
            s.add(route)
            await s.flush()

            return {
                "vehicle_id": str(vehicle.id),
                "route_id": str(route.id),
                "seg1_id": str(seg1.id),
                "seg2_id": str(seg2.id),
                "seg3_id": str(seg3.id),
                "seg4_id": str(seg4.id),
                "user_id": str(user.id),
            }


# ──────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────


async def test_plan_route_returns_valid_geometry(
    client: AsyncClient, redis_client: Redis,
) -> None:
    engine, factory = _make_factory()
    ids = await _seed_network(factory)

    token_email = _unique_email()
    await client.post("/api/v1/auth/register", json={
        "email": token_email, "password": "Pass1!",
        "full_name": "Planner", "role": "dispatcher",
    })
    token = (await client.post("/api/v1/auth/login", json={
        "email": token_email, "password": "Pass1!",
    })).json()["access_token"]

    resp = await client.post(
        "/api/v1/routes",
        json={
            "vehicle_id": ids["vehicle_id"],
            "origin_lat": A_LAT,
            "origin_lng": A_LNG,
            "destination_lat": C_LAT,
            "destination_lng": C_LNG,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["waypoints"] is not None
    assert len(body["waypoints"]) >= 2
    assert body["distance_km"] > 0
    assert body["eta_minutes"] >= 1
    assert body["vehicle_id"] == ids["vehicle_id"]
    assert body["status"] == "active"

    try:
        await engine.dispose()
    except Exception:
        pass


async def test_reroute_after_incident_changes_waypoints(
    redis_client: Redis,
) -> None:
    engine, factory = _make_factory()
    ids = await _seed_network(factory)

    repo = None
    async with factory() as session:
        async with session.begin():
            repo = RouteRepository(session)
            original = await repo.get_by_id(ids["route_id"])
            original_wps = to_shape(original.waypoints)
            original_mid_lat = list(original_wps.coords)[1][1]
            assert original_mid_lat == pytest.approx(B_LAT)

    async with factory() as session:
        async with session.begin():
            service = RoutePlanningService(
                repo=RouteRepository(session),
                osrm=OSRMClient(),
                weights=GraphWeightManager(redis_client),
                event_bus=EventBus(redis_client),
                redis=redis_client,
            )
            results = await service.reroute_affected(
                incident_id=str(uuid.uuid4()),
                affected_segment_ids=[ids["seg1_id"], ids["seg2_id"]],
                lat=B_LAT,
                lng=B_LNG,
            )
            assert len(results) >= 1

    async with factory() as session:
        updated = (await session.execute(
            select(Route).where(Route.id == ids["route_id"])
        )).scalar_one()

        assert updated.recalculation_count >= 1
        new_wps = to_shape(updated.waypoints)
        coords = list(new_wps.coords)
        mid_lat = coords[1][1]
        assert mid_lat == pytest.approx(D_LAT, abs=0.001)

    try:
        await engine.dispose()
    except Exception:
        pass


async def test_affected_routes_found_by_spatial_query(
    redis_client: Redis,
) -> None:
    engine, factory = _make_factory()
    ids = await _seed_network(factory)

    async with factory() as session:
        repo = RouteRepository(session)
        routes = await repo.get_routes_through_area(B_LAT, B_LNG, 1000)

    found_ids = [str(r.id) for r in routes]
    assert ids["route_id"] in found_ids

    try:
        await engine.dispose()
    except Exception:
        pass
