"""Random route generation for vehicle simulation."""

import random

import httpx

KYIV_CENTER = (50.45, 30.52)
KYIV_LAT_RANGE = (50.39, 50.52)
KYIV_LNG_RANGE = (30.38, 30.65)


def random_point() -> tuple[float, float]:
    return (
        random.uniform(*KYIV_LAT_RANGE),
        random.uniform(*KYIV_LNG_RANGE),
    )


async def snap_point(
    client: httpx.AsyncClient,
    osrm_url: str,
    lat: float,
    lng: float,
) -> tuple[float, float] | None:
    try:
        resp = await client.get(
            f"{osrm_url}/nearest/v1/driving/{lng},{lat}",
            timeout=5.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("code") != "Ok" or not data.get("waypoints"):
            return None
        wp = data["waypoints"][0]
        if wp.get("distance", 999) > 500:
            return None
        snapped_lng, snapped_lat = wp["location"]
        return snapped_lat, snapped_lng
    except httpx.HTTPError:
        return None


async def generate_random_endpoints(
    client: httpx.AsyncClient,
    osrm_url: str,
    count: int,
    min_distance_km: float = 2.0,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Generate `count` random origin-destination pairs snapped to roads."""
    from app.incident_generator import snap_to_road

    pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    max_attempts = count * 10

    for _ in range(max_attempts):
        if len(pairs) >= count:
            break

        origin = random_point()
        dest = random_point()

        snapped_o = await snap_point(client, osrm_url, *origin)
        snapped_d = await snap_point(client, osrm_url, *dest)

        if not snapped_o or not snapped_d:
            continue

        import math
        dlat = (snapped_o[0] - snapped_d[0]) * 111.32
        avg_lat = (snapped_o[0] + snapped_d[0]) / 2
        dlng = (snapped_o[1] - snapped_d[1]) * 111.32 * math.cos(math.radians(avg_lat))
        dist_km = (dlat**2 + dlng**2) ** 0.5

        if dist_km < min_distance_km:
            continue

        pairs.append((snapped_o, snapped_d))

    return pairs
