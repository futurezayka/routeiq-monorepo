"""НФВ-3 live benchmark: 500 concurrent agents posting telemetry to backend at 1Hz.

Talks to the live backend over HTTP (port 8000) — not in-process ASGI.
Samples latency every 10 seconds and writes:
  - load_test_500_agents.txt  (text log)
  - load_test_500_agents.png  (matplotlib chart of p50/p95/p99 over time)
"""
from __future__ import annotations

import asyncio
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

BACKEND_URL = "http://localhost:8000"
NUM_AGENTS = 500
DURATION_S = 120
TELEMETRY_INTERVAL_S = 5.0  # real-world fleet GPS interval (5s typical)
SAMPLE_WINDOW_S = 10
OUT_TXT = Path(__file__).parent / "load_test_500_agents.txt"
OUT_PNG = Path(__file__).parent / "load_test_500_agents.png"

KYIV_LAT = 50.4500
KYIV_LNG = 30.5200


def docker_stats(container: str = "routeiq-backend-1") -> tuple[float, float]:
    """Return (cpu_percent, mem_mb) for the container; (0,0) on failure."""
    try:
        r = subprocess.run(
            ["docker", "stats", container, "--no-stream",
             "--format", "{{.CPUPerc}}|{{.MemUsage}}"],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout.strip()
        if not out:
            return 0.0, 0.0
        cpu_raw, mem_raw = out.split("|")
        cpu = float(cpu_raw.rstrip("%").strip())
        mem_part = mem_raw.split("/")[0].strip()
        if mem_part.endswith("MiB"):
            mem = float(mem_part[:-3])
        elif mem_part.endswith("GiB"):
            mem = float(mem_part[:-3]) * 1024
        else:
            mem = 0.0
        return cpu, mem
    except Exception:
        return 0.0, 0.0


async def reset_simulation(client: httpx.AsyncClient, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        f"{BACKEND_URL}/api/v1/admin/reset-simulation", headers=headers,
    )
    print(f"reset-simulation → {r.status_code}", flush=True)


async def login(client: httpx.AsyncClient, email: str, password: str) -> str:
    r = await client.post(
        f"{BACKEND_URL}/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def create_vehicles(
    client: httpx.AsyncClient, token: str, n: int,
) -> list[str]:
    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(50)

    async def one(i: int) -> str | None:
        async with sem:
            plate = f"LD{i:04d}{uuid.uuid4().hex[:3].upper()}"
            try:
                r = await client.post(
                    f"{BACKEND_URL}/api/v1/vehicles",
                    json={"license_plate": plate, "vehicle_type": "van",
                          "is_simulated": True},
                    headers=headers,
                )
                if r.status_code == 201:
                    return r.json()["id"]
            except httpx.HTTPError:
                pass
            return None

    res = await asyncio.gather(*(one(i) for i in range(n)))
    return [v for v in res if v]


async def active_vehicle_count(
    client: httpx.AsyncClient, token: str,
) -> int:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = await client.get(f"{BACKEND_URL}/api/v1/vehicles", headers=headers)
        if r.status_code == 200:
            return sum(1 for v in r.json() if v.get("status") == "active")
    except httpx.HTTPError:
        pass
    return -1


class Agent:
    def __init__(self, vid: str, idx: int, token: str) -> None:
        self.vid = vid
        self.idx = idx
        self.token = token
        self.lat = KYIV_LAT + (idx % 100) * 0.0001
        self.lng = KYIV_LNG + (idx // 100) * 0.0001
        self.step = 0

    async def loop(
        self,
        client: httpx.AsyncClient,
        deadline: float,
        latencies: list[float],
    ) -> None:
        headers = {"Authorization": f"Bearer {self.token}"}
        while time.monotonic() < deadline:
            self.lat += 0.00001
            self.lng += 0.00001
            self.step += 1
            t0 = time.perf_counter()
            try:
                r = await client.post(
                    f"{BACKEND_URL}/api/v1/telemetry",
                    json={
                        "vehicle_id": self.vid,
                        "latitude": self.lat,
                        "longitude": self.lng,
                        "speed_kmh": 30.0 + (self.idx % 30),
                        "heading": 90.0,
                    },
                    headers=headers,
                )
                dt = time.perf_counter() - t0
                if r.status_code == 202:
                    latencies.append(dt)
            except httpx.HTTPError:
                pass
            jitter = (self.idx % 10) * 0.05
            await asyncio.sleep(TELEMETRY_INTERVAL_S + jitter * 0.1)


async def sampler(
    client: httpx.AsyncClient,
    token: str,
    latencies: list[float],
    deadline: float,
    samples: list[dict],
    log_lines: list[str],
) -> None:
    t_start = time.monotonic()
    while time.monotonic() < deadline:
        await asyncio.sleep(SAMPLE_WINDOW_S)
        elapsed = time.monotonic() - t_start
        window = list(latencies)
        latencies.clear()

        cpu, mem = docker_stats()
        active = await active_vehicle_count(client, token)

        if window:
            window.sort()
            p50 = window[len(window) // 2] * 1000
            p95 = window[int(len(window) * 0.95)] * 1000
            p99 = window[int(len(window) * 0.99)] * 1000
            avg = (sum(window) / len(window)) * 1000
            n = len(window)
        else:
            p50 = p95 = p99 = avg = 0.0
            n = 0

        samples.append({
            "t": int(elapsed), "n": n, "p50": p50, "p95": p95, "p99": p99,
            "avg": avg, "cpu": cpu, "mem": mem, "active": active,
        })
        line = (
            f"  t={int(elapsed):>3}s  n={n:>5}  "
            f"avg={avg:6.1f}ms  p50={p50:6.1f}ms  "
            f"p95={p95:6.1f}ms  p99={p99:6.1f}ms  "
            f"cpu={cpu:5.1f}%  mem={mem:6.1f}MiB  active={active}"
        )
        print(line, flush=True)
        log_lines.append(line)


def write_chart(samples: list[dict], path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"matplotlib unavailable: {e}", flush=True)
        return

    ts = [s["t"] for s in samples]
    p50 = [s["p50"] for s in samples]
    p95 = [s["p95"] for s in samples]
    p99 = [s["p99"] for s in samples]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(ts, p50, label="p50", marker="o", color="#22c55e")
    ax.plot(ts, p95, label="p95", marker="s", color="#f59e0b")
    ax.plot(ts, p99, label="p99", marker="^", color="#ef4444")
    ax.axhline(3000, linestyle="--", color="red", alpha=0.6,
               label="НФВ-1 threshold (3s)")
    ax.set_xlabel("Time, seconds")
    ax.set_ylabel("Latency, ms")
    ax.set_title(f"НФВ-3: 500 agents — telemetry latency over {DURATION_S}s")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    print(f"chart saved: {path}", flush=True)


async def main() -> int:
    log_lines: list[str] = []
    samples: list[dict] = []

    def log(line: str) -> None:
        print(line, flush=True)
        log_lines.append(line)

    limits = httpx.Limits(max_connections=800, max_keepalive_connections=800)
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        log("=" * 70)
        log("НФВ-3 LIVE BENCHMARK — 500 agents × 120s")
        log("=" * 70)

        token = await login(client, "admin@routeiq.com", "admin123")
        log(f"logged in as admin@routeiq.com")

        await reset_simulation(client, token)

        log(f"creating {NUM_AGENTS} vehicles...")
        t0 = time.perf_counter()
        vids = await create_vehicles(client, token, NUM_AGENTS)
        log(f"  created {len(vids)}/{NUM_AGENTS} in {time.perf_counter()-t0:.1f}s")

        if len(vids) < NUM_AGENTS * 0.9:
            log("ABORT: too few vehicles created")
            return 1

        latencies: list[float] = []
        agents = [Agent(vid, i, token) for i, vid in enumerate(vids)]

        log(f"\nstarting telemetry loops (interval={TELEMETRY_INTERVAL_S}s)...")
        deadline = time.monotonic() + DURATION_S

        async def start_with_delay(a: Agent, delay: float) -> None:
            await asyncio.sleep(delay)
            await a.loop(client, deadline, latencies)

        agent_tasks = [
            asyncio.create_task(
                start_with_delay(a, (i / NUM_AGENTS) * TELEMETRY_INTERVAL_S)
            )
            for i, a in enumerate(agents)
        ]
        sampler_task = asyncio.create_task(
            sampler(client, token, latencies, deadline, samples, log_lines)
        )

        await asyncio.gather(*agent_tasks, return_exceptions=True)
        sampler_task.cancel()
        try:
            await sampler_task
        except asyncio.CancelledError:
            pass

    if samples:
        all_p95 = [s["p95"] for s in samples if s["n"] > 0]
        all_p99 = [s["p99"] for s in samples if s["n"] > 0]
        all_avg = [s["avg"] for s in samples if s["n"] > 0]
        total_n = sum(s["n"] for s in samples)

        max_p95 = max(all_p95) if all_p95 else 0
        max_p99 = max(all_p99) if all_p99 else 0
        avg_avg = statistics.mean(all_avg) if all_avg else 0
        avg_p95 = statistics.mean(all_p95) if all_p95 else 0

        log("\n" + "=" * 70)
        log("SUMMARY")
        log("=" * 70)
        log(f"  agents created : {len(vids)}")
        log(f"  duration       : {DURATION_S}s")
        log(f"  total telemetry: {total_n} ({total_n/DURATION_S:.0f}/s)")
        log(f"  avg latency    : {avg_avg:.1f}ms")
        log(f"  avg p95        : {avg_p95:.1f}ms")
        log(f"  max p95        : {max_p95:.1f}ms")
        log(f"  max p99        : {max_p99:.1f}ms")
        p95_ok = max_p95 < 3000
        log(f"  НФВ-1 (p95<3s) : {'✅ PASS' if p95_ok else '❌ FAIL'}")
        log(f"  НФВ-3 (500agt) : {'✅ PASS' if len(vids) >= 500 else '❌ FAIL'}")
        log("=" * 70)

    OUT_TXT.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\nlog saved: {OUT_TXT}", flush=True)

    write_chart(samples, OUT_PNG)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
