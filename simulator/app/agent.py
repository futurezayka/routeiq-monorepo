import asyncio
import logging
import math
import random
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

METERS_PER_DEG_LAT = 111_320.0
METERS_PER_DEG_LNG = 111_320.0 * math.cos(math.radians(50.45))


KYIV_LAT_RANGE = (50.39, 50.52)
KYIV_LNG_RANGE = (30.38, 30.65)


@dataclass
class VirtualAgent:
    vehicle_id: str
    route: list[tuple[float, float]]
    backend_url: str
    auth_token: str = ""
    gps_noise_sigma_m: float = 2.0
    speed_min_kmh: float = 20.0
    speed_max_kmh: float = 60.0
    telemetry_interval_min: float = 3.0
    telemetry_interval_max: float = 5.0
    route_poll_interval: float = 10.0

    _lat: float = field(init=False)
    _lng: float = field(init=False)
    _wp_idx: int = field(init=False, default=1)
    _speed_kmh: float = field(init=False)
    _heading: float = field(init=False, default=0.0)
    _sent: int = field(init=False, default=0)
    _last_route_check: float = field(init=False, default=0.0)
    _route_recalc_count: int = field(init=False, default=0)
    _route_id: str = field(init=False, default="")
    _arrived: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._lat = self.route[0][0]
        self._lng = self.route[0][1]
        self._speed_kmh = random.uniform(self.speed_min_kmh, self.speed_max_kmh)

    def _distance_m(
        self, lat1: float, lng1: float, lat2: float, lng2: float,
    ) -> float:
        dlat = (lat2 - lat1) * METERS_PER_DEG_LAT
        dlng = (lng2 - lng1) * METERS_PER_DEG_LNG
        return math.sqrt(dlat**2 + dlng**2)

    def _advance(self, dt: float) -> None:
        if self._wp_idx >= len(self.route):
            self._arrived = True
            return

        tgt_lat, tgt_lng = self.route[self._wp_idx]
        dist = self._distance_m(self._lat, self._lng, tgt_lat, tgt_lng)

        move_m = (self._speed_kmh / 3.6) * dt

        if dist < 1.0 or move_m >= dist:
            self._lat = tgt_lat
            self._lng = tgt_lng
            self._wp_idx += 1
            self._speed_kmh = random.uniform(self.speed_min_kmh, self.speed_max_kmh)
        else:
            ratio = move_m / dist
            self._lat += (tgt_lat - self._lat) * ratio
            self._lng += (tgt_lng - self._lng) * ratio

        dlat = tgt_lat - self._lat
        dlng = tgt_lng - self._lng
        if abs(dlat) > 1e-9 or abs(dlng) > 1e-9:
            self._heading = math.degrees(math.atan2(dlng, dlat)) % 360

    def _noisy_position(self) -> tuple[float, float]:
        nlat = random.gauss(0, self.gps_noise_sigma_m) / METERS_PER_DEG_LAT
        nlng = random.gauss(0, self.gps_noise_sigma_m) / METERS_PER_DEG_LNG
        return self._lat + nlat, self._lng + nlng

    async def _request_new_route(
        self, client: httpx.AsyncClient, headers: dict,
    ) -> bool:
        for _ in range(5):
            dest_lat = random.uniform(*KYIV_LAT_RANGE)
            dest_lng = random.uniform(*KYIV_LNG_RANGE)
            dist_m = self._distance_m(self._lat, self._lng, dest_lat, dest_lng)
            if dist_m >= 2000:
                break

        try:
            resp = await client.post(
                f"{self.backend_url}/api/v1/routes",
                json={
                    "vehicle_id": self.vehicle_id,
                    "origin_lat": self._lat,
                    "origin_lng": self._lng,
                    "destination_lat": dest_lat,
                    "destination_lng": dest_lng,
                },
                headers=headers,
            )
            if resp.status_code != 201:
                logger.warning(
                    "Agent %s: new route request failed (%d)",
                    self.vehicle_id[:8], resp.status_code,
                )
                return False

            data = resp.json()
            waypoints = data.get("waypoints")
            if not waypoints or len(waypoints) < 2:
                return False

            self.route = [(wp[1], wp[0]) for wp in waypoints]
            self._wp_idx = 1
            self._arrived = False
            self._route_id = data.get("id", "")
            self._route_recalc_count = data.get("recalculation_count", 0)
            logger.info(
                "Agent %s: new route assigned (%d wpts, %.1f km) "
                "(%.5f,%.5f) → (%.5f,%.5f)",
                self.vehicle_id[:8], len(self.route),
                data.get("distance_km", 0),
                self._lat, self._lng, dest_lat, dest_lng,
            )
            return True
        except httpx.HTTPError as exc:
            logger.error("Agent %s: new route error: %s", self.vehicle_id[:8], exc)
            return False

    async def _check_route_update(
        self, client: httpx.AsyncClient, headers: dict,
    ) -> None:
        now = asyncio.get_event_loop().time()
        if now - self._last_route_check < self.route_poll_interval:
            return
        self._last_route_check = now
        try:
            resp = await client.get(
                f"{self.backend_url}/api/v1/vehicles/{self.vehicle_id}/route",
                headers=headers,
            )
            if resp.status_code != 200:
                return
            data = resp.json()
            new_recalc = data.get("recalculation_count", 0)
            new_route_id = data.get("id", "")
            route_changed = new_route_id != self._route_id
            recalc_changed = new_recalc > self._route_recalc_count
            if not route_changed and not recalc_changed:
                return
            self._route_recalc_count = new_recalc
            self._route_id = new_route_id
            waypoints = data.get("waypoints")
            if not waypoints or len(waypoints) < 2:
                return
            new_route = [(wp[1], wp[0]) for wp in waypoints]
            best_idx = 0
            best_dist = float("inf")
            for idx, (rlat, rlng) in enumerate(new_route):
                d = self._distance_m(self._lat, self._lng, rlat, rlng)
                if d < best_dist:
                    best_dist = d
                    best_idx = idx
            self.route = new_route
            self._wp_idx = min(best_idx + 1, len(self.route) - 1)
            self._arrived = False
            logger.info(
                "Agent %s: switched to rerouted path (%d wpts, recalc=%d), "
                "snapped to wp %d (%.0fm away)",
                self.vehicle_id[:8], len(new_route), new_recalc,
                self._wp_idx, best_dist,
            )
        except httpx.HTTPError:
            pass

    async def run(self, client: httpx.AsyncClient, duration: float) -> int:
        start = asyncio.get_event_loop().time()
        headers = {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}

        while duration <= 0 or asyncio.get_event_loop().time() - start < duration:
            interval = random.uniform(
                self.telemetry_interval_min, self.telemetry_interval_max,
            )
            await asyncio.sleep(interval)

            self._advance(interval)

            lat, lng = self._noisy_position()
            payload = {
                "vehicle_id": self.vehicle_id,
                "latitude": lat,
                "longitude": lng,
                "speed_kmh": 0.0 if self._arrived else max(0, self._speed_kmh + random.gauss(0, 2)),
                "heading": self._heading,
            }
            try:
                resp = await client.post(
                    f"{self.backend_url}/api/v1/telemetry",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 202:
                    self._sent += 1
            except httpx.HTTPError:
                pass

            if self._arrived:
                logger.info("Agent %s: arrived at destination, requesting new route", self.vehicle_id[:8])
                ok = await self._request_new_route(client, headers)
                if not ok:
                    await asyncio.sleep(5)
                continue

            await self._check_route_update(client, headers)

        return self._sent
