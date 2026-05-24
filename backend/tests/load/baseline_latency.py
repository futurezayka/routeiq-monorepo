"""НФВ-1 baseline: чиста latency POST /telemetry без насиченого load.

Імітує одного агента що шле 200 послідовних запитів і вимірює p50/p95/p99.
Це чиста backend-latency, не агрегована з sustained-load чергуванням.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import httpx

BACKEND_URL = "http://localhost:8000"
SAMPLES = 200

OUT_TXT = Path(__file__).parent / "baseline_latency.txt"


async def main() -> int:
    log_lines: list[str] = []

    def log(s: str) -> None:
        print(s, flush=True)
        log_lines.append(s)

    async with httpx.AsyncClient(timeout=10.0) as client:
        log("=" * 60)
        log("НФВ-1 BASELINE — single-agent telemetry latency")
        log("=" * 60)

        r = await client.post(
            f"{BACKEND_URL}/api/v1/auth/login",
            json={"email": "admin@routeiq.com", "password": "admin123"},
        )
        token = r.json()["access_token"]

        plate = f"BSL{uuid.uuid4().hex[:6].upper()}"
        r = await client.post(
            f"{BACKEND_URL}/api/v1/vehicles",
            json={"license_plate": plate, "vehicle_type": "van",
                  "is_simulated": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        vid = r.json()["id"]
        log(f"created vehicle {plate} → {vid[:8]}")
        log(f"sending {SAMPLES} sequential telemetry posts...")

        latencies = []
        headers = {"Authorization": f"Bearer {token}"}
        for i in range(SAMPLES):
            t0 = time.perf_counter()
            r = await client.post(
                f"{BACKEND_URL}/api/v1/telemetry",
                json={
                    "vehicle_id": vid,
                    "latitude": 50.45 + i * 0.00001,
                    "longitude": 30.52 + i * 0.00001,
                    "speed_kmh": 30.0,
                    "heading": 90.0,
                },
                headers=headers,
            )
            dt = time.perf_counter() - t0
            if r.status_code == 202:
                latencies.append(dt)

        latencies.sort()
        p50 = latencies[len(latencies) // 2] * 1000
        p95 = latencies[int(len(latencies) * 0.95)] * 1000
        p99 = latencies[int(len(latencies) * 0.99)] * 1000
        avg = (sum(latencies) / len(latencies)) * 1000

        log("")
        log("RESULTS")
        log("-" * 60)
        log(f"  samples : {len(latencies)}")
        log(f"  min     : {latencies[0]*1000:6.1f} ms")
        log(f"  avg     : {avg:6.1f} ms")
        log(f"  p50     : {p50:6.1f} ms")
        log(f"  p95     : {p95:6.1f} ms")
        log(f"  p99     : {p99:6.1f} ms")
        log(f"  max     : {latencies[-1]*1000:6.1f} ms")
        log("")
        log(f"  НФВ-1 (p95 < 3000ms): {'✅ PASS' if p95 < 3000 else '❌ FAIL'}")
        log("=" * 60)

    OUT_TXT.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\nlog saved: {OUT_TXT}", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
