"""
Telemetry latency benchmark: POST → Redis cache appearance.

NFR-1 target: p95 latency < 3 seconds from GPS event to UI availability.
This test measures the API-to-cache portion of that pipeline.
"""

import json
import time
import uuid

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

NUM_POINTS = 100
P95_THRESHOLD_S = 3.0

KYIV_LAT = 50.4500
KYIV_LNG = 30.5200


def _unique_email() -> str:
    return f"latency_{uuid.uuid4().hex[:8]}@routeiq.io"


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _setup_driver_and_vehicle(
    client: AsyncClient,
) -> tuple[str, str]:
    email = _unique_email()
    pwd = "LatP@ss123"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email, "password": pwd,
        "full_name": "Latency Driver", "role": "driver",
    })
    assert reg.status_code == 201
    token = (await client.post("/api/v1/auth/login", json={
        "email": email, "password": pwd,
    })).json()["access_token"]

    veh = await client.post(
        "/api/v1/vehicles",
        json={
            "license_plate": f"LAT{uuid.uuid4().hex[:5].upper()}",
            "vehicle_type": "van",
        },
        headers=_hdr(token),
    )
    assert veh.status_code == 201
    return token, veh.json()["id"]


async def test_telemetry_p95_latency(
    client: AsyncClient, redis_client: Redis,
) -> None:
    token, vehicle_id = await _setup_driver_and_vehicle(client)

    latencies: list[float] = []

    for i in range(NUM_POINTS):
        lat = KYIV_LAT + (i * 0.0001)
        lng = KYIV_LNG + (i * 0.00005)
        speed = 30.0 + (i % 20)

        t0 = time.perf_counter()

        resp = await client.post("/api/v1/telemetry", json={
            "vehicle_id": vehicle_id,
            "latitude": lat,
            "longitude": lng,
            "speed_kmh": speed,
            "heading": 90.0,
        }, headers=_hdr(token))
        assert resp.status_code == 202

        cached = await redis_client.get(f"vehicle:{vehicle_id}:pos")
        t1 = time.perf_counter()

        assert cached is not None, f"Point {i}: not cached after POST"
        pos = json.loads(cached)
        assert pos["lat"] == pytest.approx(lat, abs=0.001)

        latencies.append(t1 - t0)

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95_idx = int(len(latencies) * 0.95)
    p95 = latencies[p95_idx]
    p99_idx = int(len(latencies) * 0.99)
    p99 = latencies[p99_idx]
    avg = sum(latencies) / len(latencies)

    print(f"\n{'='*50}")
    print(f"Telemetry latency report ({NUM_POINTS} points)")
    print(f"  avg  = {avg*1000:.1f} ms")
    print(f"  p50  = {p50*1000:.1f} ms")
    print(f"  p95  = {p95*1000:.1f} ms")
    print(f"  p99  = {p99*1000:.1f} ms")
    print(f"  min  = {latencies[0]*1000:.1f} ms")
    print(f"  max  = {latencies[-1]*1000:.1f} ms")
    print(f"{'='*50}")

    assert p95 < P95_THRESHOLD_S, (
        f"p95 latency {p95*1000:.1f}ms exceeds {P95_THRESHOLD_S*1000:.0f}ms threshold"
    )


async def test_telemetry_cache_correctness(
    client: AsyncClient, redis_client: Redis,
) -> None:
    """Verify each telemetry POST overwrites cache with latest position."""
    token, vehicle_id = await _setup_driver_and_vehicle(client)

    positions = [
        (KYIV_LAT, KYIV_LNG, 35.0),
        (KYIV_LAT + 0.001, KYIV_LNG + 0.001, 42.0),
        (KYIV_LAT + 0.002, KYIV_LNG + 0.002, 50.0),
    ]

    for lat, lng, speed in positions:
        resp = await client.post("/api/v1/telemetry", json={
            "vehicle_id": vehicle_id,
            "latitude": lat,
            "longitude": lng,
            "speed_kmh": speed,
            "heading": 180.0,
        }, headers=_hdr(token))
        assert resp.status_code == 202

    cached = await redis_client.get(f"vehicle:{vehicle_id}:pos")
    assert cached is not None
    pos = json.loads(cached)

    last_lat, last_lng, last_speed = positions[-1]
    assert pos["lat"] == pytest.approx(last_lat, abs=0.001)
    assert pos["lng"] == pytest.approx(last_lng, abs=0.001)
    assert pos["speed"] == pytest.approx(last_speed, abs=0.1)

    ttl = await redis_client.ttl(f"vehicle:{vehicle_id}:pos")
    assert 0 < ttl <= 30, f"Expected TTL ~30s, got {ttl}"
