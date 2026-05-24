import uuid
from datetime import datetime, timedelta, timezone

import pytest
from geoalchemy2.shape import from_shape
from httpx import AsyncClient
from shapely.geometry import LineString, Point
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.incident import Incident
from app.models.route import Route
from app.models.telemetry import Telemetry
from app.models.user import User
from app.models.vehicle import Vehicle


NOW = datetime.now(timezone.utc)
HOUR_AGO = NOW - timedelta(hours=1)


def _make_factory():
    eng = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    fac = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, fac


def _unique_email() -> str:
    return f"analytics_{uuid.uuid4().hex[:8]}@routeiq.io"


async def _get_auth_headers(client: AsyncClient) -> dict:
    email = _unique_email()
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "TestP@ss1",
        "full_name": "Analytics Tester", "role": "dispatcher",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": "TestP@ss1",
    })
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_heatmap_data(factory):
    async with factory() as s:
        async with s.begin():
            await s.execute(text(
                "CREATE TABLE IF NOT EXISTS telemetry_test_default "
                "PARTITION OF telemetry DEFAULT"
            ))

            user = User(
                email=_unique_email(),
                password_hash=hash_password("seed"),
                role="driver",
                full_name="Seed Driver",
            )
            s.add(user)
            await s.flush()

            vehicle = Vehicle(
                driver_id=user.id,
                license_plate=f"AN{uuid.uuid4().hex[:4].upper()}HM",
                vehicle_type="van",
                status="active",
            )
            s.add(vehicle)
            await s.flush()

            for lat, lng, speed, ts in [
                (50.350, 30.420, 15.0, NOW - timedelta(minutes=10)),
                (50.350, 30.420, 18.0, NOW - timedelta(minutes=8)),
                (50.351, 30.421, 55.0, NOW - timedelta(minutes=5)),
            ]:
                s.add(Telemetry(
                    time=ts,
                    vehicle_id=vehicle.id,
                    latitude=lat,
                    longitude=lng,
                    speed_kmh=speed,
                    heading=0.0,
                ))


async def _seed_incident_data(factory):
    async with factory() as s:
        async with s.begin():
            user = User(
                email=_unique_email(),
                password_hash=hash_password("seed"),
                role="driver",
                full_name="Seed Reporter",
            )
            s.add(user)
            await s.flush()

            t_base = NOW - timedelta(minutes=30)
            for inc_type, severity, lat, lng, active, resolved_at, reported_at in [
                ("accident", "high", 50.45, 30.52, True, None, t_base),
                ("congestion", "low", 50.46, 30.53, True, None, t_base + timedelta(minutes=5)),
                ("accident", "medium", 50.44, 30.51, False, t_base + timedelta(minutes=40), t_base + timedelta(minutes=10)),
            ]:
                s.add(Incident(
                    reported_by=user.id,
                    type=inc_type,
                    severity=severity,
                    location=from_shape(Point(lng, lat), srid=4326),
                    is_active=active,
                    resolved_at=resolved_at,
                    reported_at=reported_at,
                ))


async def _seed_efficiency_data(factory):
    async with factory() as s:
        async with s.begin():
            await s.execute(text(
                "CREATE TABLE IF NOT EXISTS telemetry_test_default "
                "PARTITION OF telemetry DEFAULT"
            ))

            user = User(
                email=_unique_email(),
                password_hash=hash_password("seed"),
                role="driver",
                full_name="Seed Efficiency",
            )
            s.add(user)
            await s.flush()

            vehicle = Vehicle(
                driver_id=user.id,
                license_plate=f"AN{uuid.uuid4().hex[:4].upper()}EF",
                vehicle_type="van",
                status="active",
            )
            s.add(vehicle)
            await s.flush()

            route_time = NOW - timedelta(minutes=30)
            route = Route(
                vehicle_id=vehicle.id,
                status="active",
                origin=from_shape(Point(30.52, 50.45), srid=4326),
                destination=from_shape(Point(30.55, 50.43), srid=4326),
                waypoints=from_shape(
                    LineString([(30.52, 50.45), (30.53, 50.44), (30.55, 50.43)]),
                    srid=4326,
                ),
                distance_km=5.0,
                eta_minutes=20,
                recalculation_count=1,
            )
            route.created_at = route_time
            s.add(route)
            await s.flush()

            for lat, lng, speed, ts in [
                (50.450, 30.520, 40.0, route_time + timedelta(minutes=5)),
                (50.451, 30.521, 45.0, route_time + timedelta(minutes=10)),
                (50.452, 30.522, 50.0, route_time + timedelta(minutes=25)),
            ]:
                s.add(Telemetry(
                    time=ts,
                    vehicle_id=vehicle.id,
                    latitude=lat,
                    longitude=lng,
                    speed_kmh=speed,
                    heading=0.0,
                ))

            return str(route.id)


# ──────────────────── Heatmap ────────────────────


async def test_heatmap_returns_congestion_points(client: AsyncClient) -> None:
    engine, factory = _make_factory()
    try:
        await _seed_heatmap_data(factory)
        headers = await _get_auth_headers(client)

        resp = await client.get("/api/v1/analytics/heatmap", params={
            "from": HOUR_AGO.isoformat(),
            "to": NOW.isoformat(),
        }, headers=headers)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["points"]) >= 1

        congested = [p for p in body["points"] if p["congestion_level"] > 0.5]
        assert len(congested) >= 1, "Should have at least one congested cell (speed ~16.5 km/h)"
    finally:
        await engine.dispose()


async def test_heatmap_empty_range_returns_no_points(client: AsyncClient) -> None:
    headers = await _get_auth_headers(client)
    far_future = "2099-01-01T00:00:00Z"
    resp = await client.get("/api/v1/analytics/heatmap", params={
        "from": far_future,
        "to": "2099-01-02T00:00:00Z",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["points"] == []


# ──────────────── Incident Stats ─────────────────


async def test_incident_stats_aggregates_correctly(client: AsyncClient) -> None:
    engine, factory = _make_factory()
    try:
        await _seed_incident_data(factory)
        headers = await _get_auth_headers(client)

        resp = await client.get("/api/v1/analytics/incidents", params={
            "from": HOUR_AGO.isoformat(),
            "to": NOW.isoformat(),
        }, headers=headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 3
        assert body["by_type"].get("accident", 0) >= 2
        assert body["by_type"].get("congestion", 0) >= 1
        assert body["active_count"] >= 2
        assert body["resolved_count"] >= 1
        assert body["avg_resolution_minutes"] is not None
        assert body["avg_resolution_minutes"] > 0
    finally:
        await engine.dispose()


async def test_incident_stats_empty_range(client: AsyncClient) -> None:
    headers = await _get_auth_headers(client)
    resp = await client.get("/api/v1/analytics/incidents", params={
        "from": "2099-01-01T00:00:00Z",
        "to": "2099-01-02T00:00:00Z",
    }, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["by_type"] == {}


# ─────────────── Fleet Efficiency ────────────────


async def test_fleet_efficiency_calculates_ratio(client: AsyncClient) -> None:
    engine, factory = _make_factory()
    try:
        route_id = await _seed_efficiency_data(factory)
        headers = await _get_auth_headers(client)

        resp = await client.get("/api/v1/analytics/efficiency", params={
            "from": HOUR_AGO.isoformat(),
            "to": NOW.isoformat(),
        }, headers=headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["routes_total"] >= 1

        matching = [r for r in body["routes"] if r["route_id"] == route_id]
        assert len(matching) == 1
        r = matching[0]
        assert r["planned_eta"] == 20
        assert r["actual_minutes"] == pytest.approx(25.0, abs=1.0)
        assert r["efficiency"] is not None
        assert r["efficiency"] == pytest.approx(20 / 25, abs=0.05)
    finally:
        await engine.dispose()


async def test_fleet_efficiency_empty_range(client: AsyncClient) -> None:
    headers = await _get_auth_headers(client)
    resp = await client.get("/api/v1/analytics/efficiency", params={
        "from": "2099-01-01T00:00:00Z",
        "to": "2099-01-02T00:00:00Z",
    }, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["routes_total"] == 0
    assert body["routes"] == []
