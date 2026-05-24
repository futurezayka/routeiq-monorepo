import json
import uuid

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis


def _unique_email() -> str:
    return f"driver_{uuid.uuid4().hex[:8]}@routeiq.io"


async def _register_and_login(client: AsyncClient) -> tuple[str, str]:
    """Register a user, login, return (token, user_id)."""
    email = _unique_email()
    password = "StrongP@ss1"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "Test Driver",
        "role": "driver",
    })
    user_id = reg.json()["id"]
    login = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password,
    })
    return login.json()["access_token"], user_id


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_vehicle(
    client: AsyncClient, token: str, plate: str | None = None,
) -> dict:
    plate = plate or f"AA{uuid.uuid4().hex[:4].upper()}BB"
    resp = await client.post(
        "/api/v1/vehicles",
        json={"license_plate": plate, "vehicle_type": "van"},
        headers=_auth(token),
    )
    return resp.json()


async def test_register_vehicle_returns_201(client: AsyncClient) -> None:
    token, user_id = await _register_and_login(client)
    plate = f"XX{uuid.uuid4().hex[:4].upper()}ZZ"

    resp = await client.post(
        "/api/v1/vehicles",
        json={"license_plate": plate, "vehicle_type": "truck"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["license_plate"] == plate
    assert body["vehicle_type"] == "truck"
    assert body["driver_id"] == user_id
    assert body["status"] == "offline"


async def test_list_vehicles_returns_registered(client: AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    plate = f"LL{uuid.uuid4().hex[:4].upper()}LL"
    await _create_vehicle(client, token, plate)

    resp = await client.get("/api/v1/vehicles", headers=_auth(token))
    assert resp.status_code == 200
    plates = [v["license_plate"] for v in resp.json()]
    assert plate in plates


async def test_ingest_telemetry_returns_202(client: AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    vehicle = await _create_vehicle(client, token)
    vehicle_id = vehicle["id"]

    resp = await client.post("/api/v1/telemetry", json={
        "vehicle_id": vehicle_id,
        "latitude": 50.4501,
        "longitude": 30.5234,
        "speed_kmh": 55.0,
        "heading": 90.0,
    }, headers=_auth(token))
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


async def test_ingest_telemetry_caches_position_in_redis(
    client: AsyncClient, redis_client: Redis,
) -> None:
    token, _ = await _register_and_login(client)
    vehicle = await _create_vehicle(client, token)
    vehicle_id = vehicle["id"]

    await client.post("/api/v1/telemetry", json={
        "vehicle_id": vehicle_id,
        "latitude": 50.45,
        "longitude": 30.52,
        "speed_kmh": 40.0,
        "heading": 180.0,
    }, headers=_auth(token))

    cached = await redis_client.get(f"vehicle:{vehicle_id}:pos")
    assert cached is not None
    data = json.loads(cached)
    assert data["lat"] == pytest.approx(50.45)
    assert data["lng"] == pytest.approx(30.52)
    assert data["speed"] == pytest.approx(40.0)

    await redis_client.delete(f"vehicle:{vehicle_id}:pos")


async def test_ingest_telemetry_publishes_to_stream(
    client: AsyncClient, redis_client: Redis,
) -> None:
    token, _ = await _register_and_login(client)
    vehicle = await _create_vehicle(client, token)
    vehicle_id = vehicle["id"]

    await client.post("/api/v1/telemetry", json={
        "vehicle_id": vehicle_id,
        "latitude": 50.46,
        "longitude": 30.53,
        "speed_kmh": 60.0,
        "heading": 270.0,
    }, headers=_auth(token))

    messages = await redis_client.xrevrange("stream:telemetry", count=10)
    found = False
    for _msg_id, fields in messages:
        if fields.get("vehicle_id") == vehicle_id:
            assert float(fields["lat"]) == pytest.approx(50.46)
            assert float(fields["lng"]) == pytest.approx(30.53)
            assert float(fields["speed"]) == pytest.approx(60.0)
            found = True
            break
    assert found, "Telemetry event not found in stream:telemetry"

    await redis_client.delete("stream:telemetry")
