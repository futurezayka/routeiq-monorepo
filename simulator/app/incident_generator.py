import asyncio
import logging
import random

import httpx

logger = logging.getLogger(__name__)

INCIDENT_TYPES = [
    ("congestion", 0.40),
    ("accident", 0.30),
    ("roadwork", 0.20),
    ("weather", 0.10),
]

SEVERITY_BY_TYPE = {
    "accident": ["medium", "high"],
    "congestion": ["low", "medium"],
    "roadwork": ["low", "medium"],
    "weather": ["medium", "high"],
}


async def snap_to_road(
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


class IncidentGenerator:
    def __init__(
        self,
        backend_url: str,
        auth_token: str,
        osrm_url: str = "http://osrm:5000",
        incident_lambda: float = 2.0,
        route_waypoints: list[list[tuple[float, float]]] | None = None,
        max_active: int = 8,
        resolve_after_s: tuple[float, float] = (180, 300),
    ) -> None:
        self._backend_url = backend_url
        self._token = auth_token
        self._osrm_url = osrm_url
        self._lambda = incident_lambda
        self._routes = route_waypoints or []
        self._count = 0
        self._max_active = max_active
        self._resolve_after_s = resolve_after_s
        self._active_incidents: list[tuple[str, float]] = []

    def _pick_type(self) -> str:
        r = random.random()
        cumulative = 0.0
        for t, w in INCIDENT_TYPES:
            cumulative += w
            if r <= cumulative:
                return t
        return INCIDENT_TYPES[-1][0]

    async def _pick_road_point(
        self, client: httpx.AsyncClient,
    ) -> tuple[float, float] | None:
        """Ask backend for a random point ON a major road.

        Returns None on any failure — caller falls back to a route waypoint.
        """
        try:
            resp = await client.get(
                f"{self._backend_url}/api/v1/admin/random-road-point",
                params={"n": 1},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=3.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not isinstance(data, list) or not data:
                return None
            p = data[0]
            return float(p["lat"]), float(p["lng"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    def _pick_route_waypoint(self) -> tuple[float, float] | None:
        """Fallback: pick an actual waypoint of an active route (no offset).

        Waypoints come from OSRM and are guaranteed snapped to the road
        graph, so the resulting incident is always on a drivable segment.
        """
        if not self._routes:
            return None
        route = random.choice(self._routes)
        if not route:
            return None
        # Stay away from endpoints (origin/destination) so the incident
        # doesn't visually overlap the start/dest marker.
        if len(route) > 10:
            idx = random.randint(5, len(route) - 6)
        else:
            idx = random.randint(0, len(route) - 1)
        return route[idx]

    async def run(self, client: httpx.AsyncClient, duration: float) -> int:
        start = asyncio.get_event_loop().time()
        headers = {"Authorization": f"Bearer {self._token}"}

        if not self._routes:
            logger.warning("No routes provided — incident generator idle")
            return 0

        while duration <= 0 or asyncio.get_event_loop().time() - start < duration:
            now = asyncio.get_event_loop().time()
            await self._resolve_stale(client, headers, now)

            wait = random.expovariate(self._lambda / 60.0)
            if duration > 0:
                remaining = duration - (now - start)
                if wait > remaining:
                    break
            await asyncio.sleep(wait)

            if len(self._active_incidents) >= self._max_active:
                continue

            incident_type = self._pick_type()
            severity = random.choice(SEVERITY_BY_TYPE[incident_type])

            # PostGIS-sampled point ON a major road (motorway/trunk/primary/
            # secondary/tertiary). 100% on a real road, no water/parks.
            road_pt = await self._pick_road_point(client)
            location_source = "postgis"
            if road_pt is None:
                # Backend unavailable or no major roads — fall back to a
                # route waypoint (also guaranteed snapped to OSRM road).
                road_pt = self._pick_route_waypoint()
                location_source = "waypoint"
                if road_pt is None:
                    logger.warning("No incident location source available")
                    continue
                # Best-effort OSRM nearest only for the fallback path.
                snapped = await snap_to_road(
                    client, self._osrm_url, road_pt[0], road_pt[1],
                )
                if snapped:
                    road_pt = snapped
                    location_source = "waypoint+osrm"
            lat, lng = road_pt

            payload = {
                "type": incident_type,
                "severity": severity,
                "latitude": lat,
                "longitude": lng,
                "is_simulated": True,
            }

            try:
                resp = await client.post(
                    f"{self._backend_url}/api/v1/incidents",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 201:
                    self._count += 1
                    inc_id = resp.json().get("id", "")
                    resolve_at = now + random.uniform(*self._resolve_after_s)
                    self._active_incidents.append((inc_id, resolve_at))
                    logger.info(
                        "Incident #%d: %s/%s at (%.4f, %.4f) src=%s [active=%d/%d]",
                        self._count, incident_type, severity, lat, lng,
                        location_source,
                        len(self._active_incidents), self._max_active,
                    )
                else:
                    logger.warning(
                        "Incident rejected: %d — %s",
                        resp.status_code, resp.text[:120],
                    )
            except httpx.HTTPError as exc:
                logger.error("Incident error: %s", exc)

        return self._count

    async def _resolve_stale(
        self, client: httpx.AsyncClient, headers: dict, now: float,
    ) -> None:
        still_active: list[tuple[str, float]] = []
        for inc_id, resolve_at in self._active_incidents:
            if now >= resolve_at:
                try:
                    resp = await client.patch(
                        f"{self._backend_url}/api/v1/incidents/{inc_id}/resolve",
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        logger.info("Auto-resolved incident %s", inc_id[:8])
                    else:
                        logger.warning(
                            "Resolve incident %s: %d", inc_id[:8], resp.status_code,
                        )
                except httpx.HTTPError:
                    pass
            else:
                still_active.append((inc_id, resolve_at))
        self._active_incidents = still_active
