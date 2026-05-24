"""Try to fetch GTFS-Realtime from Kyiv. Falls back gracefully if unavailable."""
from __future__ import annotations

import json
import time
from pathlib import Path

KYIV_GTFS_RT_URLS = [
    "https://transport.kyivcity.gov.ua/gtfs-rt/vehicle_position",
    "http://195.230.155.42/vehicle_position",
]

OUTPUT = Path(__file__).parent / "kyiv_gtfs_samples.jsonl"


def try_fetch() -> list[dict] | None:
    try:
        import httpx
        import gtfs_realtime_pb2  # type: ignore
    except ImportError as e:
        print(f"  ⚠ deps not installed ({e}); skipping real-data attempt")
        return None

    feed = gtfs_realtime_pb2.FeedMessage()
    for url in KYIV_GTFS_RT_URLS:
        try:
            r = httpx.get(url, timeout=10)
            r.raise_for_status()
            feed.ParseFromString(r.content)
            vehicles = []
            for entity in feed.entity:
                if entity.HasField("vehicle"):
                    v = entity.vehicle
                    vehicles.append({
                        "vehicle_id": v.vehicle.id,
                        "lat": v.position.latitude,
                        "lng": v.position.longitude,
                        "bearing": v.position.bearing,
                        "speed": v.position.speed,
                        "timestamp": v.timestamp,
                    })
            print(f"  ✓ Fetched {len(vehicles)} vehicles from {url}")
            return vehicles
        except Exception as e:
            print(f"  ✗ {url} → {e}")
            continue
    return None


def main() -> bool:
    OUTPUT.parent.mkdir(exist_ok=True)
    print("Attempting to collect Kyiv GTFS-RT (60s)...")

    samples: list[dict] = []
    start = time.time()
    attempts = 0
    while time.time() - start < 60 and attempts < 3:
        vs = try_fetch()
        attempts += 1
        if vs:
            samples.extend(vs)
        time.sleep(20)

    if samples:
        with OUTPUT.open("a") as f:
            for s in samples:
                f.write(json.dumps(s) + "\n")
        print(f"Collected {len(samples)} samples → {OUTPUT}")
        return True
    print("⚠ No real Kyiv data — synthetic dataset will be used")
    return False


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 0)
