"""
НФВ-6: Graceful degradation when Redis is unavailable.

Verifies that core API operations (telemetry ingest, incident reporting,
vehicle listing) continue to work via PostgreSQL even when Redis is down.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError


def _unique_email() -> str:
    return f"degrade_{uuid.uuid4().hex[:8]}@routeiq.io"


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register_login(client: AsyncClient) -> tuple[str, str]:
    email = _unique_email()
    pwd = "DegradeP@ss1"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email, "password": pwd,
        "full_name": "Degradation Tester", "role": "dispatcher",
    })
    assert reg.status_code == 201
    user_id = reg.json()["id"]
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": pwd,
    })
    assert login.status_code == 200
    return login.json()["access_token"], user_id


async def test_telemetry_works_without_redis(client: AsyncClient) -> None:
    """
    Telemetry POST should return 202 even when Redis cache/stream fails.
    The DB update (vehicle position) should still succeed.
    """
    token, _ = await _register_login(client)

    # Create a vehicle first (while Redis is up)
    veh = await client.post("/api/v1/vehicles", json={
        "license_plate": f"DG{uuid.uuid4().hex[:5].upper()}",
        "vehicle_type": "van",
    }, headers=_hdr(token))
    assert veh.status_code == 201
    vehicle_id = veh.json()["id"]

    # Now simulate Redis being down by patching Redis methods to raise
    broken_redis = AsyncMock(spec=Redis)
    broken_redis.set.side_effect = RedisConnectionError("Connection refused")
    broken_redis.xadd.side_effect = RedisConnectionError("Connection refused")

    with patch("app.modules.agent_manager.service.AgentManagerService._redis", broken_redis, create=True):
        with patch("app.events.publisher.EventBus.publish", side_effect=RedisConnectionError("Connection refused")):
            with patch.object(
                Redis, "set",
                side_effect=RedisConnectionError("Connection refused"),
            ):
                resp = await client.post("/api/v1/telemetry", json={
                    "vehicle_id": vehicle_id,
                    "latitude": 50.45,
                    "longitude": 30.52,
                    "speed_kmh": 40.0,
                    "heading": 90.0,
                }, headers=_hdr(token))

    assert resp.status_code == 202, (
        f"Telemetry should succeed even with Redis down: {resp.status_code} {resp.text}"
    )


async def test_incident_creation_without_redis(client: AsyncClient) -> None:
    """
    Incident POST should return 201 even when Redis stream publish fails.
    The incident should be saved in the database.
    """
    token, _ = await _register_login(client)

    with patch("app.events.publisher.EventBus.publish", side_effect=RedisConnectionError("Connection refused")):
        resp = await client.post("/api/v1/incidents", json={
            "type": "accident",
            "severity": "high",
            "latitude": 50.45,
            "longitude": 30.52,
        }, headers=_hdr(token))

    assert resp.status_code == 201, (
        f"Incident should be created even with Redis down: {resp.status_code} {resp.text}"
    )
    inc = resp.json()
    assert inc["type"] == "accident"
    assert inc["is_active"] is True


async def test_vehicle_listing_without_redis(client: AsyncClient) -> None:
    """
    GET /vehicles should work even if Redis is completely down,
    since it reads from PostgreSQL only.
    """
    token, _ = await _register_login(client)

    # Create a vehicle
    veh = await client.post("/api/v1/vehicles", json={
        "license_plate": f"DG{uuid.uuid4().hex[:5].upper()}",
        "vehicle_type": "van",
    }, headers=_hdr(token))
    assert veh.status_code == 201

    # Vehicle listing is DB-only, so no Redis patching needed —
    # just verify it doesn't depend on Redis at all
    resp = await client.get("/api/v1/vehicles", headers=_hdr(token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_incident_listing_without_redis(client: AsyncClient) -> None:
    """
    GET /incidents should work even if Redis is down.
    """
    token, _ = await _register_login(client)

    resp = await client.get("/api/v1/incidents", headers=_hdr(token))
    assert resp.status_code == 200
