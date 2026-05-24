"""Route planning service — NetworkX A* primary, OSRM fallback."""

import asyncio
import json
import logging
import time
import uuid

from geoalchemy2.shape import from_shape, to_shape
from redis.asyncio import Redis
from shapely.geometry import LineString, Point
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.events.publisher import EventBus
from app.modules.route_planning.calculator import (
    RouteCalculator,
    haversine,
)
from app.modules.route_planning.detour_config import DETOUR_MAX_RATIO
from app.modules.route_planning.graph_weights import GraphWeightManager
from app.modules.route_planning.incident_config import (
    IMPACT_RADIUS_M,
    REROUTING_SEARCH_RADIUS_M,
)
from app.modules.route_planning.osrm_client import OSRMClient
from app.modules.route_planning.polyline_config import DP_TOLERANCE_DEG
from app.modules.route_planning.repository import RouteRepository
from app.schemas.route import RouteCreate, RouteResponse

logger = logging.getLogger(__name__)

REROUTE_CONCURRENCY = 5

_calculator = RouteCalculator()


def _smooth_line(line: LineString) -> LineString:
    """Douglas-Peucker smoothing applied just before persistence.

    Runs AFTER OSRM match (which re-injects dense geometry) so the
    waypoint count actually shrinks in the DB. Tolerance is the
    polyline_config DP_TOLERANCE_DEG (~5.5 m at Kyiv latitude).
    """
    coords = list(line.coords)
    if len(coords) <= 15:
        return line
    simplified = line.simplify(DP_TOLERANCE_DEG, preserve_topology=False)
    new_coords = list(simplified.coords)
    if len(new_coords) < 5:
        return line
    return LineString(new_coords)


class RoutePlanningService:
    def __init__(
        self,
        repo: RouteRepository,
        osrm: OSRMClient,
        weights: GraphWeightManager,
        event_bus: EventBus,
        redis: Redis,
    ) -> None:
        self._repo = repo
        self._osrm = osrm
        self._weights = weights
        self._event_bus = event_bus
        self._redis = redis
        self._calc = _calculator

    def _to_response(self, route) -> RouteResponse:
        o = to_shape(route.origin)
        d = to_shape(route.destination)
        wps = None
        if route.waypoints:
            wps = [list(c) for c in to_shape(route.waypoints).coords]
        return RouteResponse(
            id=route.id,
            vehicle_id=route.vehicle_id,
            status=route.status,
            origin_lat=o.y,
            origin_lng=o.x,
            destination_lat=d.y,
            destination_lng=d.x,
            waypoints=wps,
            distance_km=route.distance_km,
            eta_minutes=route.eta_minutes,
            recalculation_count=route.recalculation_count,
            created_at=route.created_at,
        )

    async def list_routes(self) -> list[RouteResponse]:
        routes = await self._repo.list_active()
        return [self._to_response(r) for r in routes]

    async def plan_route(self, data: RouteCreate) -> RouteResponse:
        """NetworkX A* (primary) -> OSRM (fallback) -> direct line (last resort)."""
        o_lat, o_lng = data.origin_lat, data.origin_lng
        d_lat, d_lng = data.destination_lat, data.destination_lng

        straight_m = haversine(o_lat, o_lng, d_lat, d_lng)
        if straight_m < 500:
            raise ValidationError(
                f"Route too short ({straight_m:.0f}m). "
                "Origin and destination must be at least 500m apart.",
            )

        await self._repo.cancel_active_for_vehicle(data.vehicle_id)

        mid_lat = (o_lat + d_lat) / 2
        mid_lng = (o_lng + d_lng) / 2
        incidents = await self._repo.get_active_incidents_nearby(
            mid_lat, mid_lng, radius_m=REROUTING_SEARCH_RADIUS_M,
        )
        if incidents:
            await self._refresh_incident_weights(incidents)

        straight_km = straight_m / 1000
        max_detour_km = max(straight_km * 2.5, 3.0)

        wp_line = dist_km = eta_min = None

        # --- PRIMARY: NetworkX A* + OSRM match ---
        t0 = time.monotonic()
        session = self._repo._session
        await self._calc.ensure_graph(session)
        weights = await self._calc.fetch_weights(self._weights)

        path_result = await self._calc.find_path(
            session, o_lat, o_lng, d_lat, d_lng, weights,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        if path_result and len(path_result.coords) >= 2:
            matched = await self._osrm.match(path_result.coords)
            if matched and len(matched.waypoints) >= 2:
                wp_line = LineString(matched.waypoints)
                dist_km = round(matched.distance_m / 1000, 2)
                avg_spd = (
                    (matched.distance_m / 1000) / (matched.duration_s / 3600)
                    if matched.duration_s > 0
                    else 30
                )
                eta_min = max(1, round(dist_km / avg_spd * 60))
                logger.info(
                    "plan_route: NX A* + OSRM match, dist=%.1fkm, "
                    "eta=%dmin, pts=%d, elapsed=%.0fms",
                    dist_km, eta_min, len(matched.waypoints), elapsed_ms,
                )
            else:
                wp_line = LineString(path_result.coords)
                dist_km = round(path_result.distance_m / 1000, 2)
                eta_min = path_result.eta_minutes
                logger.info(
                    "plan_route: NX A* raw, dist=%.1fkm, "
                    "eta=%dmin, elapsed=%.0fms",
                    dist_km, eta_min, elapsed_ms,
                )

            if dist_km is not None and dist_km > max_detour_km:
                logger.warning(
                    "plan_route: A* %.1fkm > cap %.1fkm, falling to OSRM",
                    dist_km, max_detour_km,
                )
                wp_line = dist_km = eta_min = None

        # --- FALLBACK: OSRM direct ---
        if wp_line is None:
            osrm_result = await self._osrm.route(
                (o_lng, o_lat), (d_lng, d_lat),
            )
            if osrm_result:
                wp_line = LineString(osrm_result.waypoints)
                dist_km = round(osrm_result.distance_m / 1000, 2)
                avg_spd = (
                    (osrm_result.distance_m / 1000)
                    / (osrm_result.duration_s / 3600)
                    if osrm_result.duration_s > 0
                    else 30
                )
                eta_min = max(1, round(dist_km / avg_spd * 60))
                logger.info(
                    "plan_route: OSRM fallback, dist=%.1fkm", dist_km,
                )

        # --- LAST RESORT: direct line ---
        if wp_line is None:
            logger.warning(
                "No route (%s,%s)->(%s,%s), direct fallback",
                o_lat, o_lng, d_lat, d_lng,
            )
            wp_line = LineString([(o_lng, o_lat), (d_lng, d_lat)])
            dist_km = round(straight_km, 2)
            eta_min = max(1, int(straight_km / 50 * 60))

        route = await self._repo.create({
            "vehicle_id": data.vehicle_id,
            "origin": from_shape(Point(o_lng, o_lat), srid=4326),
            "destination": from_shape(Point(d_lng, d_lat), srid=4326),
            "waypoints": from_shape(wp_line, srid=4326),
            "distance_km": round(dist_km, 2),
            "eta_minutes": eta_min,
        })
        return self._to_response(route)

    async def get_route(self, route_id: uuid.UUID) -> RouteResponse:
        route = await self._repo.get_by_id(route_id)
        if not route:
            raise NotFoundError("Route not found")
        return self._to_response(route)

    async def get_active_route(
        self, vehicle_id: uuid.UUID,
    ) -> RouteResponse:
        route = await self._repo.get_active_by_vehicle(vehicle_id)
        if not route:
            raise NotFoundError("No active route")
        return self._to_response(route)

    async def reroute_affected(
        self,
        incident_id: str,
        affected_segment_ids: list[str],
        lat: float,
        lng: float,
        severity: str = "medium",
        incident_type: str = "accident",
        action: str = "new",
    ) -> list[RouteResponse]:
        # 1) Mark or clear incident zone weights — radius scales with severity
        impact_radius = IMPACT_RADIUS_M.get(severity, IMPACT_RADIUS_M["medium"])
        nearby_segments = await self._repo.get_nearby_segments(
            lat, lng, radius_m=impact_radius,
        )
        seg_ids_for_weight = [str(s.id) for s in nearby_segments]

        if action == "resolved":
            if seg_ids_for_weight:
                await self._weights.clear_incident_zone(seg_ids_for_weight)
            logger.info(
                "Reroute (resolved): incident=%s, cleared %d segments",
                incident_id, len(seg_ids_for_weight),
            )
        else:
            if seg_ids_for_weight:
                await self._weights.mark_incident_zone(
                    seg_ids_for_weight, severity,
                )
            logger.info(
                "Reroute: incident=%s, marked %d segments, severity=%s",
                incident_id, len(seg_ids_for_weight), severity,
            )

        # 2) Refresh weights for ALL active incidents
        all_incidents = await self._repo.get_all_active_incidents()
        if all_incidents:
            await self._refresh_incident_weights(all_incidents)

        # 3) Find affected routes
        if action == "resolved":
            nearby = await self._repo.get_routes_through_area(
                lat, lng, 3000,
            )
            rerouted = await self._repo.get_rerouted_routes()
            seen_ids = {r.id for r in nearby}
            routes = list(nearby)
            for r in rerouted:
                if r.id not in seen_ids:
                    routes.append(r)
        else:
            routes = await self._repo.get_routes_through_area(
                lat, lng, 1500,
            )
        logger.info(
            "Found %d affected routes for incident %s",
            len(routes), incident_id,
        )

        results: list[RouteResponse] = []
        affected_route_ids: list[str] = []

        if not routes:
            await self._publish_ws(
                incident_id, affected_route_ids,
                seg_ids_for_weight, lat, lng, severity, incident_type,
            )
            return results

        # Pre-fetch vehicle positions
        pos_pipe = self._redis.pipeline()
        for route in routes:
            pos_pipe.get(f"vehicle:{route.vehicle_id}:pos")
        pos_raws = await pos_pipe.execute()

        session = self._repo._session
        await self._calc.ensure_graph(session)
        weights = await self._calc.fetch_weights(self._weights)

        sem = asyncio.Semaphore(REROUTE_CONCURRENCY)

        async def _reroute_one(route, pos_raw):
            async with sem:
                return await self._reroute_single(
                    session, route, pos_raw, weights, severity,
                )

        tasks = [
            _reroute_one(r, pos_raws[i]) for i, r in enumerate(routes)
        ]
        computed = await asyncio.gather(*tasks, return_exceptions=True)

        for i, route in enumerate(routes):
            result = computed[i]
            if isinstance(result, Exception):
                logger.exception(
                    "Reroute failed for route %s: %s",
                    str(route.id)[:8], result,
                )
                continue
            if result:
                results.append(self._to_response(result))
                affected_route_ids.append(str(route.id))

            await self._event_bus.publish("stream:route-updates", {
                "route_id": str(route.id),
                "incident_id": incident_id,
                "reason": "incident_reroute",
            })

        await self._publish_ws(
            incident_id, affected_route_ids,
            seg_ids_for_weight, lat, lng, severity, incident_type,
        )
        return results

    async def _reroute_single(
        self,
        session: AsyncSession,
        route,
        pos_raw: bytes | None,
        weights: dict[str, float],
        severity: str,
    ):
        dest_pt = to_shape(route.destination)
        if pos_raw:
            pos_data = json.loads(pos_raw)
            start_lat = float(pos_data["lat"])
            start_lng = float(pos_data["lng"])
        else:
            origin_pt = to_shape(route.origin)
            start_lat, start_lng = origin_pt.y, origin_pt.x

        old_dist = route.distance_km or 0

        new_line: LineString | None = None
        new_dist = 0.0
        new_eta = 0
        method = "unchanged"

        # Candidate 1: NetworkX A* (naturally avoids weighted incident areas)
        path_result = await self._calc.find_path(
            session, start_lat, start_lng,
            dest_pt.y, dest_pt.x, weights,
        )
        if path_result and len(path_result.coords) >= 2:
            matched = await self._osrm.match(path_result.coords)
            if matched and len(matched.waypoints) >= 2:
                new_line = LineString(matched.waypoints)
                new_dist = matched.distance_m / 1000
                avg_spd = (
                    new_dist / (matched.duration_s / 3600)
                    if matched.duration_s > 0
                    else 30
                )
                new_eta = max(1, round(new_dist / avg_spd * 60))
                method = "nx_astar_matched"
            else:
                new_line = LineString(path_result.coords)
                new_dist = path_result.distance_m / 1000
                new_eta = path_result.eta_minutes
                method = "nx_astar_raw"

        # Candidate 2: OSRM alternatives (if A* failed or produced worse route)
        if new_line is None:
            alternatives = await self._osrm.route_alternatives(
                (start_lng, start_lat), (dest_pt.x, dest_pt.y), 3,
            )
            for j, alt in enumerate(alternatives):
                alt_line = LineString(alt.waypoints)
                alt_dist = alt.distance_m / 1000
                avg_spd = (
                    alt_dist / (alt.duration_s / 3600)
                    if alt.duration_s > 0
                    else 30
                )
                alt_eta = max(1, round(alt_dist / avg_spd * 60))
                if new_line is None or alt_dist < new_dist:
                    new_line = alt_line
                    new_dist = alt_dist
                    new_eta = alt_eta
                    method = f"osrm_alt_{j}"

        if new_line is None:
            return None

        # Pin endpoints
        coords = list(new_line.coords)
        coords[0] = (start_lng, start_lat)
        if haversine(
            coords[-1][1], coords[-1][0], dest_pt.y, dest_pt.x,
        ) > 20:
            coords.append((dest_pt.x, dest_pt.y))
        else:
            coords[-1] = (dest_pt.x, dest_pt.y)
        new_line = LineString(coords)

        new_dist = round(new_dist, 2)
        detour_ratio = new_dist / old_dist if old_dist > 0 else 0
        detour_cap = DETOUR_MAX_RATIO.get(severity, DETOUR_MAX_RATIO["medium"])

        if old_dist > 0 and detour_ratio > detour_cap:
            logger.info(
                "REROUTE skipped route=%s severity=%s method=%s "
                "detour_ratio=%.2fx > cap=%.2fx (keep original)",
                str(route.id)[:8], severity, method, detour_ratio, detour_cap,
            )
            return None

        logger.info(
            "REROUTE route=%s vehicle=%s severity=%s method=%s "
            "old_dist=%.1fkm new_dist=%.1fkm "
            "detour_ratio=%.2fx (cap=%.2fx)",
            str(route.id)[:8], str(route.vehicle_id)[:8],
            severity, method, old_dist, new_dist, detour_ratio, detour_cap,
        )

        return await self._repo.update_route(
            route.id,
            from_shape(new_line, srid=4326),
            new_dist, new_eta,
        )

    async def _refresh_incident_weights(self, incidents) -> None:
        by_severity: dict[str, list[str]] = {}
        for inc in incidents:
            pt = to_shape(inc.location)
            radius_m = IMPACT_RADIUS_M.get(
                inc.severity, IMPACT_RADIUS_M["medium"],
            )
            segs = await self._repo.get_nearby_segments(
                pt.y, pt.x, radius_m=radius_m,
            )
            for s in segs:
                by_severity.setdefault(inc.severity, []).append(str(s.id))
        for sev, seg_ids in by_severity.items():
            await self._weights.mark_incident_zone(seg_ids, sev)

    async def _publish_ws(
        self,
        incident_id: str,
        affected_route_ids: list[str],
        seg_ids_for_weight: list[str],
        lat: float,
        lng: float,
        severity: str,
        incident_type: str,
    ) -> None:
        await self._redis.publish("ws:route-updates", json.dumps({
            "incident_id": incident_id,
            "affected_routes": affected_route_ids,
            "affected_segments": seg_ids_for_weight,
            "severity": severity,
            "incident_type": incident_type,
        }))
        await self._redis.publish("ws:incidents", json.dumps({
            "incident_id": incident_id,
            "lat": lat,
            "lng": lng,
            "type": "new_incident",
            "severity": severity,
            "incident_type": incident_type,
        }))
