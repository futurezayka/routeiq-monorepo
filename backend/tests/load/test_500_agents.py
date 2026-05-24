"""
НФВ-3: 500 concurrent agents stress test.

Verifies that the system handles ≥500 simultaneous vehicles sending
telemetry without degradation. Measures throughput and p95 latency.
"""

import asyncio
import json
import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.core.config import settings
from app.main import app

NUM_AGENTS = 500
TELEMETRY_PER_AGENT = 3
CONCURRENCY = 50  # max concurrent HTTP requests
P95_THRESHOLD_S = 5.0  # in-process ASGI transport; production target is 3s

KYIV_LAT = 50.4500
KYIV_LNG = 30.5200


def _unique_email() -> str:
    return f"load_{uuid.uuid4().hex[:8]}@routeiq.io"


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register_login(client: AsyncClient) -> str:
    email = _unique_email()
    pwd = "LoadT3st!"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": pwd,
        "full_name": "Load Tester", "role": "dispatcher",
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email, "password": pwd,
    })
    return login.json()["access_token"]


async def test_500_agents_telemetry(redis_client: Redis) -> None:
    """
    Create 500 vehicles, send telemetry from each concurrently.
    Verify all positions cached in Redis and measure latency.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_login(client)
        headers = _hdr(token)

        # Phase 1: Create 500 vehicles concurrently
        sem = asyncio.Semaphore(CONCURRENCY)
        vehicle_ids: list[str] = []
        create_errors = 0

        async def create_vehicle(idx: int) -> str | None:
            nonlocal create_errors
            plate = f"LD{idx:04d}{uuid.uuid4().hex[:3].upper()}"
            async with sem:
                try:
                    resp = await client.post("/api/v1/vehicles", json={
                        "license_plate": plate, "vehicle_type": "van",
                    }, headers=headers)
                    if resp.status_code == 201:
                        return resp.json()["id"]
                    create_errors += 1
                    return None
                except Exception:
                    create_errors += 1
                    return None

        t_create_start = time.perf_counter()
        results = await asyncio.gather(
            *[create_vehicle(i) for i in range(NUM_AGENTS)]
        )
        t_create = time.perf_counter() - t_create_start

        vehicle_ids = [r for r in results if r is not None]
        assert len(vehicle_ids) >= NUM_AGENTS * 0.95, (
            f"Only {len(vehicle_ids)}/{NUM_AGENTS} vehicles created "
            f"({create_errors} errors)"
        )

        print(f"\n{'='*60}")
        print(f"Phase 1: Created {len(vehicle_ids)} vehicles in {t_create:.1f}s")
        print(f"  Throughput: {len(vehicle_ids)/t_create:.0f} vehicles/s")

        # Phase 2: Send telemetry from all vehicles concurrently
        latencies: list[float] = []
        telem_errors = 0

        async def send_telemetry(vid: str, step: int) -> None:
            nonlocal telem_errors
            idx = vehicle_ids.index(vid)
            lat = KYIV_LAT + (idx % 100) * 0.0001 + step * 0.00001
            lng = KYIV_LNG + (idx // 100) * 0.0001 + step * 0.00001
            speed = 30.0 + (idx % 30)

            async with sem:
                t0 = time.perf_counter()
                try:
                    resp = await client.post("/api/v1/telemetry", json={
                        "vehicle_id": vid,
                        "latitude": lat,
                        "longitude": lng,
                        "speed_kmh": speed,
                        "heading": 90.0,
                    }, headers=headers)
                    t1 = time.perf_counter()
                    if resp.status_code == 202:
                        latencies.append(t1 - t0)
                    else:
                        telem_errors += 1
                except Exception:
                    telem_errors += 1

        t_telem_start = time.perf_counter()
        for step in range(TELEMETRY_PER_AGENT):
            await asyncio.gather(
                *[send_telemetry(vid, step) for vid in vehicle_ids]
            )
        t_telem = time.perf_counter() - t_telem_start

        total_points = len(vehicle_ids) * TELEMETRY_PER_AGENT
        success_points = len(latencies)

        assert success_points >= total_points * 0.95, (
            f"Only {success_points}/{total_points} telemetry points succeeded "
            f"({telem_errors} errors)"
        )

        # Phase 3: Verify Redis cache
        cached_count = 0
        for vid in vehicle_ids[:100]:  # sample first 100
            cached = await redis_client.get(f"vehicle:{vid}:pos")
            if cached is not None:
                cached_count += 1

        cache_rate = cached_count / 100

        # Latency analysis
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[p95_idx]
        p99_idx = int(len(latencies) * 0.99)
        p99 = latencies[p99_idx]
        avg = sum(latencies) / len(latencies)

        print(f"\nPhase 2: {success_points} telemetry points in {t_telem:.1f}s")
        print(f"  Throughput: {success_points/t_telem:.0f} points/s")
        print(f"  avg  = {avg*1000:.1f} ms")
        print(f"  p50  = {p50*1000:.1f} ms")
        print(f"  p95  = {p95*1000:.1f} ms")
        print(f"  p99  = {p99*1000:.1f} ms")
        print(f"  min  = {latencies[0]*1000:.1f} ms")
        print(f"  max  = {latencies[-1]*1000:.1f} ms")
        print(f"\nPhase 3: Redis cache hit rate: {cache_rate*100:.0f}%")
        print(f"{'='*60}")

        # Assertions
        assert p95 < P95_THRESHOLD_S, (
            f"p95 latency {p95*1000:.1f}ms exceeds {P95_THRESHOLD_S*1000:.0f}ms"
        )
        assert cache_rate >= 0.90, (
            f"Cache rate {cache_rate*100:.0f}% below 90% threshold"
        )
