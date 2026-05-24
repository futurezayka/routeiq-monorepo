import asyncio
import logging
import math
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_M_PER_DEG_LAT = 111_320.0


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Equirectangular distance in meters using average latitude of two points."""
    avg_lat_rad = math.radians((a[1] + b[1]) / 2)
    cos_lat = math.cos(avg_lat_rad)
    dx = (a[0] - b[0]) * _M_PER_DEG_LAT * cos_lat
    dy = (a[1] - b[1]) * _M_PER_DEG_LAT
    return math.sqrt(dx * dx + dy * dy)


def _remove_spurs(
    pts: list[tuple[float, float]],
    close_threshold_m: float = 60.0,
    max_spur_len: int = 40,
) -> list[tuple[float, float]]:
    """Remove spur detours: route leaves main road and returns nearby."""
    result: list[tuple[float, float]] = []
    i = 0
    n = len(pts)
    while i < n:
        result.append(pts[i])
        found = False
        for k in range(min(max_spur_len, n - i - 2), 1, -1):
            j = i + k
            if j >= n:
                continue
            if _dist_m(pts[i], pts[j]) < close_threshold_m:
                i = j
                found = True
                break
        if not found:
            i += 1
    return result


@dataclass
class RouteGeometry:
    waypoints: list[tuple[float, float]]
    distance_m: float
    duration_s: float


@dataclass
class NearestPoint:
    latitude: float
    longitude: float
    distance_m: float


class OSRMClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.OSRM_URL).rstrip("/")

    async def route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> RouteGeometry | None:
        coords = f"{origin[0]},{origin[1]};{destination[0]},{destination[1]}"
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{self._base_url}/route/v1/driving/{coords}",
                        params={"overview": "full", "geometries": "geojson"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("code") != "Ok":
                        logger.warning("OSRM code=%s for %s", data.get("code"), coords)
                        return None
                    r = data["routes"][0]
                    raw = [tuple(c) for c in r["geometry"]["coordinates"]]
                    return RouteGeometry(
                        waypoints=_remove_spurs(raw),
                        distance_m=r["distance"],
                        duration_s=r["duration"],
                    )
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                last_exc = exc
                if attempt < 3:
                    await asyncio.sleep(0.5 * attempt)
        logger.warning("OSRM route failed after 3 attempts for %s: %s", coords, last_exc)
        return None

    async def route_alternatives(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        num_alternatives: int = 3,
    ) -> list[RouteGeometry]:
        coords = f"{origin[0]},{origin[1]};{destination[0]},{destination[1]}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._base_url}/route/v1/driving/{coords}",
                    params={
                        "overview": "full",
                        "geometries": "geojson",
                        "alternatives": str(num_alternatives),
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != "Ok":
                    return []
                results = []
                for r in data["routes"]:
                    raw = [tuple(c) for c in r["geometry"]["coordinates"]]
                    results.append(RouteGeometry(
                        waypoints=_remove_spurs(raw),
                        distance_m=r["distance"],
                        duration_s=r["duration"],
                    ))
                return results
        except (httpx.HTTPError, KeyError, IndexError):
            return []

    async def route_via(
        self,
        origin: tuple[float, float],
        via: list[tuple[float, float]],
        destination: tuple[float, float],
    ) -> RouteGeometry | None:
        points = [origin, *via, destination]
        coords = ";".join(f"{p[0]},{p[1]}" for p in points)
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{self._base_url}/route/v1/driving/{coords}",
                        params={"overview": "full", "geometries": "geojson"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("code") != "Ok":
                        return None
                    r = data["routes"][0]
                    raw = [tuple(c) for c in r["geometry"]["coordinates"]]
                    return RouteGeometry(
                        waypoints=_remove_spurs(raw),
                        distance_m=r["distance"],
                        duration_s=r["duration"],
                    )
            except (httpx.HTTPError, KeyError, IndexError):
                if attempt < 3:
                    await asyncio.sleep(0.3 * attempt)
        return None

    async def match(
        self,
        coordinates: list[tuple[float, float]],
        radius_m: float = 25,
    ) -> RouteGeometry | None:
        """OSRM map-matching: snaps a coordinate trace to the road network."""
        if len(coordinates) < 2:
            return None
        max_coords = 100
        if len(coordinates) > max_coords:
            step = len(coordinates) / (max_coords - 1)
            sampled = [coordinates[int(i * step)] for i in range(max_coords - 1)]
            sampled.append(coordinates[-1])
            coordinates = sampled

        coords_str = ";".join(f"{c[0]},{c[1]}" for c in coordinates)
        radiuses = ";".join(str(int(radius_m)) for _ in coordinates)
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(
                        f"{self._base_url}/match/v1/driving/{coords_str}",
                        params={
                            "overview": "full",
                            "geometries": "geojson",
                            "radiuses": radiuses,
                            "gaps": "ignore",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("code") != "Ok":
                        return None
                    matchings = data.get("matchings", [])
                    if not matchings:
                        return None
                    all_coords: list[tuple[float, float]] = []
                    total_distance = 0.0
                    total_duration = 0.0
                    for m in matchings:
                        mc = [tuple(c) for c in m["geometry"]["coordinates"]]
                        all_coords.extend(mc)
                        total_distance += m["distance"]
                        total_duration += m["duration"]
                    if len(all_coords) < 2:
                        return None
                    return RouteGeometry(
                        waypoints=_remove_spurs(all_coords),
                        distance_m=total_distance,
                        duration_s=total_duration,
                    )
            except (httpx.HTTPError, KeyError, IndexError):
                if attempt < 3:
                    await asyncio.sleep(0.3 * attempt)
        return None

    async def nearest(self, lat: float, lng: float) -> NearestPoint | None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._base_url}/nearest/v1/driving/{lng},{lat}",
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != "Ok":
                    return None
                wp = data["waypoints"][0]
                return NearestPoint(
                    latitude=wp["location"][1],
                    longitude=wp["location"][0],
                    distance_m=wp["distance"],
                )
        except (httpx.HTTPError, KeyError, IndexError):
            return None

    async def table(
        self,
        origins: list[tuple[float, float]],
        destinations: list[tuple[float, float]],
    ) -> list[list[float | None]] | None:
        all_pts = origins + destinations
        coords = ";".join(f"{p[0]},{p[1]}" for p in all_pts)
        src_idx = ";".join(str(i) for i in range(len(origins)))
        dst_idx = ";".join(str(i) for i in range(len(origins), len(all_pts)))
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/table/v1/driving/{coords}",
                    params={"sources": src_idx, "destinations": dst_idx},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != "Ok":
                    return None
                return data["durations"]
        except (httpx.HTTPError, KeyError):
            return None
