"""НФВ-4 throughput benchmark: ≥10 000 events/sec через Redis Streams.

Публікує 10 000 подій у stream:telemetry за один раунд (asyncio.gather),
повторює 10 разів і виводить min/avg/max throughput.
Може бути запущено і як pytest, і як standalone:
    python -m tests.load.test_event_throughput
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

from redis.asyncio import ConnectionPool, Redis

REDIS_URL = "redis://localhost:6379/0"
EVENTS_PER_ROUND = 10_000
ROUNDS = 10
STREAM = "stream:telemetry"
OUT_TXT = Path(__file__).parent / "load_test_10k_events.txt"


async def publish_batch(redis: Redis, n: int) -> float:
    """Push n events to STREAM concurrently. Returns wall time in seconds."""
    pipe = redis.pipeline(transaction=False)
    for i in range(n):
        pipe.xadd(STREAM, {
            "vehicle_id": f"bench-{i}",
            "lat": "50.45",
            "lng": "30.52",
            "speed": "30",
            "heading": "0",
            "timestamp": "bench",
        })
    t0 = time.perf_counter()
    await pipe.execute()
    return time.perf_counter() - t0


async def run_benchmark() -> dict:
    pool = ConnectionPool.from_url(REDIS_URL, decode_responses=True)
    redis = Redis(connection_pool=pool)
    await redis.ping()

    log_lines: list[str] = []

    def log(s: str) -> None:
        print(s, flush=True)
        log_lines.append(s)

    log("=" * 60)
    log(f"НФВ-4 LIVE BENCHMARK — {ROUNDS}×{EVENTS_PER_ROUND} events to {STREAM}")
    log("=" * 60)

    rates: list[float] = []
    durations: list[float] = []
    initial_len = await redis.xlen(STREAM)
    log(f"  stream:telemetry length before: {initial_len}")

    log("")
    log(f"{'round':<8}{'events':<10}{'time, s':<10}{'events/sec':<15}")
    log("-" * 45)

    for r in range(1, ROUNDS + 1):
        dt = await publish_batch(redis, EVENTS_PER_ROUND)
        rate = EVENTS_PER_ROUND / dt if dt > 0 else 0
        rates.append(rate)
        durations.append(dt)
        log(f"{r:<8}{EVENTS_PER_ROUND:<10}{dt:<10.3f}{rate:<15.0f}")

    final_len = await redis.xlen(STREAM)
    log("")
    log(f"  stream:telemetry length after:  {final_len}")
    log(f"  delta (events added):           {final_len - initial_len}")

    min_r = min(rates)
    max_r = max(rates)
    avg_r = statistics.mean(rates)

    log("")
    log("SUMMARY")
    log("-" * 45)
    log(f"  min throughput : {min_r:>10.0f} events/sec")
    log(f"  avg throughput : {avg_r:>10.0f} events/sec")
    log(f"  max throughput : {max_r:>10.0f} events/sec")
    log(f"  median         : {statistics.median(rates):>10.0f} events/sec")
    log(f"  total events   : {ROUNDS * EVENTS_PER_ROUND}")
    log(f"  total wall time: {sum(durations):>10.3f} s")
    log("")
    nfv_ok = avg_r >= 10_000
    log(f"  НФВ-4 (avg ≥ 10k/s): {'✅ PASS' if nfv_ok else '❌ FAIL'}")
    log("=" * 60)

    await redis.aclose()
    await pool.aclose()

    OUT_TXT.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\nlog saved: {OUT_TXT}", flush=True)

    return {
        "min": min_r,
        "avg": avg_r,
        "max": max_r,
        "passed": nfv_ok,
        "rates": rates,
        "durations": durations,
    }


async def test_event_throughput_at_least_10k_per_sec() -> None:
    result = await run_benchmark()
    assert result["avg"] >= 10_000, (
        f"avg throughput {result['avg']:.0f} events/sec < 10 000"
    )


if __name__ == "__main__":
    res = asyncio.run(run_benchmark())
    sys.exit(0 if res["passed"] else 1)
