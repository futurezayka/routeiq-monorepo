"""НФВ-2 timing: incident → route-update propagation time через pipeline."""
from __future__ import annotations

import asyncio
import json
import statistics
import time
import uuid
from pathlib import Path

import httpx
from redis.asyncio import ConnectionPool, Redis

BACKEND_URL = "http://localhost:8000"
REDIS_URL = "redis://localhost:6379/0"
NUM_TRIALS = 5
OUT_TXT = Path(__file__).parent / "reroute_timing.txt"


async def login(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"email": "admin@routeiq.com", "password": "admin123"},
    )
    return r.json()["access_token"]


async def setup_vehicle_with_route(
    client: httpx.AsyncClient, token: str,
) -> tuple[str, dict]:
    h = {"Authorization": f"Bearer {token}"}
    plate = f"NFV2{uuid.uuid4().hex[:5].upper()}"
    rv = await client.post(
        f"{BACKEND_URL}/api/v1/vehicles",
        json={"license_plate": plate, "vehicle_type": "van", "is_simulated": True},
        headers=h,
    )
    vid = rv.json()["id"]
    rp = await client.post(
        f"{BACKEND_URL}/api/v1/routes",
        json={
            "vehicle_id": vid,
            "origin_lat": 50.45, "origin_lng": 30.52,
            "destination_lat": 50.48, "destination_lng": 30.55,
        },
        headers=h,
    )
    return vid, rp.json()


async def measure_one(
    client: httpx.AsyncClient, redis: Redis, token: str, lat: float, lng: float,
) -> float:
    """POST an incident; return seconds until matching route-update appears."""
    h = {"Authorization": f"Bearer {token}"}
    last_id = await redis.xrevrange("stream:route-updates", count=1)
    cursor = last_id[0][0] if last_id else "0-0"

    t0 = time.perf_counter()
    r = await client.post(
        f"{BACKEND_URL}/api/v1/incidents",
        json={"type": "accident", "severity": "high",
              "latitude": lat, "longitude": lng, "is_simulated": True},
        headers=h,
    )
    inc_id = r.json()["id"]

    deadline = t0 + 15
    while time.monotonic() < deadline:
        new_entries = await redis.xread({"stream:route-updates": cursor},
                                         count=200, block=200)
        for _name, entries in new_entries or []:
            for msg_id, data in entries:
                cursor = msg_id
                if data.get("incident_id") == inc_id:
                    return time.perf_counter() - t0
    return -1.0


async def main() -> int:
    log_lines = []

    def log(s: str) -> None:
        print(s, flush=True)
        log_lines.append(s)

    pool = ConnectionPool.from_url(REDIS_URL, decode_responses=True)
    redis = Redis(connection_pool=pool)
    await redis.ping()

    async with httpx.AsyncClient(timeout=30.0) as client:
        log("=" * 60)
        log("НФВ-2 LIVE TIMING — incident → route-update propagation")
        log("=" * 60)

        token = await login(client)
        log("setting up 50 vehicles with routes near Kyiv center...")
        for _ in range(50):
            await setup_vehicle_with_route(client, token)

        log(f"running {NUM_TRIALS} trials...")
        timings: list[float] = []
        log("")
        log(f"{'trial':<8}{'incident location':<22}{'time, s':<10}")
        log("-" * 45)
        for i in range(NUM_TRIALS):
            lat = 50.45 + (i * 0.003)
            lng = 30.52 + (i * 0.003)
            dt = await measure_one(client, redis, token, lat, lng)
            timings.append(dt)
            location = f"({lat:.4f},{lng:.4f})"
            time_str = f"{dt:.3f}" if dt > 0 else "TIMEOUT"
            log(f"{i+1:<8}{location:<22}{time_str:<10}")
            await asyncio.sleep(1.0)

        success = [t for t in timings if t > 0]
        log("")
        if success:
            log("RESULTS")
            log("-" * 45)
            log(f"  trials : {len(success)}/{NUM_TRIALS} successful")
            log(f"  min    : {min(success):.3f} s")
            log(f"  avg    : {statistics.mean(success):.3f} s")
            log(f"  median : {statistics.median(success):.3f} s")
            log(f"  max    : {max(success):.3f} s")
            avg_t = statistics.mean(success)
            log(f"  НФВ-2 (max < 10s): {'✅ PASS' if max(success) < 10 else '❌ FAIL'}")
        log("=" * 60)

    await redis.aclose()
    await pool.aclose()
    OUT_TXT.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\nlog saved: {OUT_TXT}", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
