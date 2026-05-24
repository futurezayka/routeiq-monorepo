"""
ФВ-9: Simulator integration test.

Verifies the simulator workflow: register → create vehicles → send telemetry
→ report incidents. Exercises the same API contract the simulator uses.
"""

import json
import random
import uuid

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis


KYIV_LAT = 50.4500
KYIV_LNG = 30.5200


def _unique_email() -> str:
    return f"sim_{uuid.uuid4().hex[:8]}@routeiq.local"


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _sim_register_login(client: AsyncClient) -> str:
    """Mimic simulator's ensure_auth: register + login."""
    email = _unique_email()
    pwd = "sim-secret-2026"

    reg = await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": pwd,
        "full_name": "Simulator Bot",
        "role": "dispatcher",
    })
    assert reg.status_code == 201, f"Simulator register failed: {reg.text}"

    login = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": pwd,
    })
    assert login.status_code == 200, f"Simulator login failed: {login.text}"
    return login.json()["access_token"]


async def test_simulator_vehicle_creation(client: AsyncClient) -> None:
    """Simulator creates vehicles with SIM- prefix plates and is_simulated=true."""
    token = await _sim_register_login(client)
    num_agents = 3
    vehicle_ids = []

    suffix = uuid.uuid4().hex[:4].upper()
    for i in range(num_agents):
        plate = f"SIM-{i + 1:03d}-{suffix}"
        resp = await client.post(
            "/api/v1/vehicles",
            json={"license_plate": plate, "vehicle_type": "van", "is_simulated": True},
            headers=_hdr(token),
        )
        assert resp.status_code == 201, f"Vehicle {plate} creation failed: {resp.text}"
        vehicle = resp.json()
        vehicle_ids.append(vehicle["id"])
        assert vehicle["license_plate"] == plate

    assert len(vehicle_ids) == num_agents

    # Verify all vehicles visible in listing
    listing = await client.get("/api/v1/vehicles", headers=_hdr(token))
    assert listing.status_code == 200
    listed_ids = {v["id"] for v in listing.json()}
    for vid in vehicle_ids:
        assert vid in listed_ids, f"Vehicle {vid} not in listing"


async def test_simulator_telemetry_flow(
    client: AsyncClient, redis_client: Redis,
) -> None:
    """Simulator sends telemetry with vehicle_id, lat, lng, speed, heading."""
    token = await _sim_register_login(client)

    plate = f"SIM-TEL-{uuid.uuid4().hex[:4].upper()}"
    veh = await client.post(
        "/api/v1/vehicles",
        json={"license_plate": plate, "vehicle_type": "van", "is_simulated": True},
        headers=_hdr(token),
    )
    assert veh.status_code == 201
    vehicle_id = veh.json()["id"]

    # Simulate 10 telemetry points along a route
    route = [
        (KYIV_LAT + i * 0.001, KYIV_LNG + i * 0.0005)
        for i in range(10)
    ]

    for i, (lat, lng) in enumerate(route):
        speed = random.uniform(20.0, 60.0)
        heading = 90.0 + random.gauss(0, 5)
        payload = {
            "vehicle_id": vehicle_id,
            "latitude": lat,
            "longitude": lng,
            "speed_kmh": speed,
            "heading": heading,
        }

        resp = await client.post(
            "/api/v1/telemetry",
            json=payload,
            headers=_hdr(token),
        )
        assert resp.status_code == 202, f"Telemetry {i} failed: {resp.text}"

    # Verify position cached in Redis
    cached = await redis_client.get(f"vehicle:{vehicle_id}:pos")
    assert cached is not None, "Vehicle position not cached in Redis"
    pos = json.loads(cached)
    assert "lat" in pos and "lng" in pos
    assert pos["lat"] == pytest.approx(route[-1][0], abs=0.01)
    assert pos["lng"] == pytest.approx(route[-1][1], abs=0.01)


async def test_simulator_incident_reporting(client: AsyncClient) -> None:
    """Simulator reports incidents with various types and severities."""
    token = await _sim_register_login(client)

    incidents_to_create = [
        ("congestion", "low", KYIV_LAT + 0.01, KYIV_LNG + 0.01),
        ("accident", "high", KYIV_LAT - 0.01, KYIV_LNG),
        ("roadwork", "medium", KYIV_LAT, KYIV_LNG + 0.02),
        ("weather", "high", KYIV_LAT + 0.02, KYIV_LNG - 0.01),
    ]

    incident_ids = []
    for inc_type, severity, lat, lng in incidents_to_create:
        resp = await client.post(
            "/api/v1/incidents",
            json={
                "type": inc_type,
                "severity": severity,
                "latitude": lat,
                "longitude": lng,
                "is_simulated": True,
            },
            headers=_hdr(token),
        )
        assert resp.status_code == 201, f"Incident {inc_type}/{severity} failed: {resp.text}"
        inc = resp.json()
        incident_ids.append(inc["id"])
        assert inc["type"] == inc_type
        assert inc["severity"] == severity
        assert inc["is_active"] is True
        assert inc["is_simulated"] is True

    # Verify incidents in listing
    listing = await client.get("/api/v1/incidents", headers=_hdr(token))
    assert listing.status_code == 200
    listed_ids = {i["id"] for i in listing.json()}
    for iid in incident_ids:
        assert iid in listed_ids, f"Incident {iid} not in listing"


async def test_simulator_full_workflow(
    client: AsyncClient, redis_client: Redis,
) -> None:
    """
    Full simulator workflow: register → vehicles → telemetry → incidents.
    Mirrors the actual simulator's run_simulation() sequence.
    """
    token = await _sim_register_login(client)
    num_agents = 5

    # Step 1: Create vehicles
    suffix = uuid.uuid4().hex[:4].upper()
    vehicle_ids = []
    for i in range(num_agents):
        plate = f"SIM-{i + 1:03d}-{suffix}"
        resp = await client.post(
            "/api/v1/vehicles",
            json={"license_plate": plate, "vehicle_type": "van", "is_simulated": True},
            headers=_hdr(token),
        )
        assert resp.status_code == 201
        vehicle_ids.append(resp.json()["id"])

    assert len(vehicle_ids) == num_agents

    # Step 2: Each vehicle sends telemetry (5 points each)
    telemetry_count = 0
    for idx, vid in enumerate(vehicle_ids):
        for step in range(5):
            lat = KYIV_LAT + idx * 0.005 + step * 0.001
            lng = KYIV_LNG + idx * 0.003 + step * 0.0005
            speed = random.uniform(20.0, 60.0)
            heading = random.uniform(0, 360)

            resp = await client.post("/api/v1/telemetry", json={
                "vehicle_id": vid,
                "latitude": lat,
                "longitude": lng,
                "speed_kmh": speed,
                "heading": heading,
            }, headers=_hdr(token))
            assert resp.status_code == 202
            telemetry_count += 1

    assert telemetry_count == num_agents * 5

    # Step 3: Report incidents
    incident_types = ["congestion", "accident", "roadwork", "weather"]
    severities = {"congestion": "low", "accident": "high", "roadwork": "medium", "weather": "high"}
    incident_count = 0

    for inc_type in incident_types:
        lat = random.uniform(50.38, 50.52)
        lng = random.uniform(30.39, 30.63)
        resp = await client.post("/api/v1/incidents", json={
            "type": inc_type,
            "severity": severities[inc_type],
            "latitude": lat,
            "longitude": lng,
            "is_simulated": True,
        }, headers=_hdr(token))
        assert resp.status_code == 201
        incident_count += 1

    assert incident_count == 4

    # Verify final state: all vehicles have cached positions
    for vid in vehicle_ids:
        cached = await redis_client.get(f"vehicle:{vid}:pos")
        assert cached is not None, f"Vehicle {vid} position not cached"

    # Verify incidents exist
    incidents = await client.get("/api/v1/incidents", headers=_hdr(token))
    assert incidents.status_code == 200
    simulated = [i for i in incidents.json() if i["is_simulated"]]
    assert len(simulated) >= 4
