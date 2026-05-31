"""Unit tests for RoutePlanningService — all deps mocked."""

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point

from app.core.exceptions import NotFoundError, ValidationError
from app.modules.route_planning.calculator import PathResult
from app.modules.route_planning.osrm_client import RouteGeometry
from app.modules.route_planning.service import RoutePlanningService, _smooth_line
from app.schemas.route import RouteCreate


# ── helpers ──────────────────────────────────────────────────

def _route(
    vid=None,
    origin=(30.5, 50.4),
    dest=(30.55, 50.45),
    wp_coords=None,
    dist=2.0,
    eta=6,
    recount=0,
    status="active",
):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.vehicle_id = vid or uuid.uuid4()
    r.status = status
    r.origin = from_shape(Point(*origin), srid=4326)
    r.destination = from_shape(Point(*dest), srid=4326)
    if wp_coords:
        r.waypoints = from_shape(LineString(wp_coords), srid=4326)
    else:
        r.waypoints = None
    r.distance_km = dist
    r.eta_minutes = eta
    r.recalculation_count = recount
    r.created_at = datetime(2026, 1, 1)
    return r


def _path(coords=None, seg_ids=None, dist_m=1500, eta_min=5):
    return PathResult(
        coords=coords or [(30.5, 50.4), (30.51, 50.41), (30.55, 50.45)],
        segment_ids=seg_ids or ["s1", "s2"],
        distance_m=dist_m,
        eta_minutes=eta_min,
    )


def _geom(waypoints=None, dist=1500, dur=120):
    return RouteGeometry(
        waypoints=waypoints or [(30.5, 50.4), (30.51, 50.41), (30.55, 50.45)],
        distance_m=dist,
        duration_s=dur,
    )


@pytest.fixture
def svc():
    repo = AsyncMock()
    repo._session = AsyncMock()
    repo.list_active = AsyncMock(return_value=[])
    repo.cancel_active_for_vehicle = AsyncMock()
    repo.get_active_incidents_nearby = AsyncMock(return_value=[])
    repo.get_all_active_incidents = AsyncMock(return_value=[])
    repo.get_nearby_segments = AsyncMock(return_value=[])
    repo.get_routes_through_area = AsyncMock(return_value=[])
    repo.get_rerouted_routes = AsyncMock(return_value=[])
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_active_by_vehicle = AsyncMock(return_value=None)

    osrm = AsyncMock()
    osrm.match = AsyncMock(return_value=None)
    osrm.route = AsyncMock(return_value=None)
    osrm.route_alternatives = AsyncMock(return_value=[])

    weights = AsyncMock()
    event_bus = AsyncMock()

    redis = AsyncMock()
    redis.publish = AsyncMock()
    pipe = AsyncMock()
    pipe.get = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline = MagicMock(return_value=pipe)

    calc = AsyncMock()
    calc.ensure_graph = AsyncMock()
    calc.fetch_weights = AsyncMock(return_value={})
    calc.find_path = AsyncMock(return_value=None)

    service = RoutePlanningService(repo, osrm, weights, event_bus, redis)
    service._calc = calc

    return service, repo, osrm, weights, event_bus, redis, calc


def _data(o_lat=50.40, o_lng=30.50, d_lat=50.45, d_lng=30.55):
    return RouteCreate(
        vehicle_id=uuid.uuid4(),
        origin_lat=o_lat,
        origin_lng=o_lng,
        destination_lat=d_lat,
        destination_lng=d_lng,
    )


# ── _smooth_line ──────────────────────────────────────────────

def test_smooth_line_short_unchanged():
    line = LineString([(i, 0) for i in range(10)])
    assert _smooth_line(line) is line


def test_smooth_line_simplifies_long():
    coords = [(i * 0.01, (i % 3) * 0.001) for i in range(20)]
    line = LineString(coords)
    result = _smooth_line(line)
    assert len(list(result.coords)) <= len(coords)


def test_smooth_line_keeps_original_if_oversimplified():
    coords = [(i * 0.0000001, 0) for i in range(20)]
    line = LineString(coords)
    result = _smooth_line(line)
    assert list(result.coords) == coords


# ── _to_response ──────────────────────────────────────────────

def test_to_response_with_waypoints(svc):
    service = svc[0]
    r = _route(wp_coords=[(30.5, 50.4), (30.51, 50.41)])
    resp = service._to_response(r)
    assert resp.distance_km == 2.0
    assert resp.waypoints is not None
    assert len(resp.waypoints) == 2


def test_to_response_without_waypoints(svc):
    service = svc[0]
    r = _route()
    resp = service._to_response(r)
    assert resp.waypoints is None


# ── list_routes ───────────────────────────────────────────────

async def test_list_routes_empty(svc):
    service, repo, *_ = svc
    assert await service.list_routes() == []


async def test_list_routes_returns_mapped(svc):
    service, repo, *_ = svc
    repo.list_active.return_value = [_route(), _route()]
    result = await service.list_routes()
    assert len(result) == 2


# ── get_route ─────────────────────────────────────────────────

async def test_get_route_found(svc):
    service, repo, *_ = svc
    r = _route()
    repo.get_by_id.return_value = r
    resp = await service.get_route(r.id)
    assert resp.id == r.id


async def test_get_route_not_found(svc):
    service, *_ = svc
    with pytest.raises(NotFoundError):
        await service.get_route(uuid.uuid4())


# ── get_active_route ──────────────────────────────────────────

async def test_get_active_found(svc):
    service, repo, *_ = svc
    r = _route()
    repo.get_active_by_vehicle.return_value = r
    resp = await service.get_active_route(r.vehicle_id)
    assert resp.vehicle_id == r.vehicle_id


async def test_get_active_not_found(svc):
    service, *_ = svc
    with pytest.raises(NotFoundError):
        await service.get_active_route(uuid.uuid4())


# ── plan_route ────────────────────────────────────────────────

async def test_plan_route_too_short(svc):
    service, *_ = svc
    data = _data(o_lat=50.450, o_lng=30.520, d_lat=50.4501, d_lng=30.5201)
    with pytest.raises(ValidationError, match="too short"):
        await service.plan_route(data)


async def test_plan_route_astar_with_osrm_match(svc):
    service, repo, osrm, _, _, _, calc = svc
    calc.find_path.return_value = _path()
    osrm.match.return_value = _geom()
    created = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])
    repo.create.return_value = created

    resp = await service.plan_route(_data())
    assert resp.id == created.id
    repo.create.assert_awaited_once()


async def test_plan_route_astar_raw_when_match_fails(svc):
    service, repo, osrm, _, _, _, calc = svc
    calc.find_path.return_value = _path()
    osrm.match.return_value = None
    created = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])
    repo.create.return_value = created

    resp = await service.plan_route(_data())
    repo.create.assert_awaited_once()
    create_arg = repo.create.call_args[0][0]
    assert create_arg["distance_km"] == 1.5


async def test_plan_route_astar_too_long_falls_to_osrm(svc):
    service, repo, osrm, _, _, _, calc = svc
    calc.find_path.return_value = _path(dist_m=500_000)
    osrm.match.return_value = _geom(dist=500_000)
    osrm.route.return_value = _geom(dist=2000, dur=180)
    created = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])
    repo.create.return_value = created

    await service.plan_route(_data())
    osrm.route.assert_awaited_once()


async def test_plan_route_osrm_fallback(svc):
    service, repo, osrm, _, _, _, calc = svc
    calc.find_path.return_value = None
    osrm.route.return_value = _geom(dist=2000, dur=150)
    created = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])
    repo.create.return_value = created

    await service.plan_route(_data())
    osrm.route.assert_awaited_once()
    create_arg = repo.create.call_args[0][0]
    assert create_arg["distance_km"] == 2.0


async def test_plan_route_osrm_zero_duration(svc):
    service, repo, osrm, _, _, _, calc = svc
    calc.find_path.return_value = None
    osrm.route.return_value = _geom(dist=2000, dur=0)
    created = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])
    repo.create.return_value = created

    await service.plan_route(_data())
    create_arg = repo.create.call_args[0][0]
    assert create_arg["eta_minutes"] >= 1


async def test_plan_route_direct_line_fallback(svc):
    service, repo, osrm, _, _, _, calc = svc
    calc.find_path.return_value = None
    osrm.route.return_value = None
    created = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])
    repo.create.return_value = created

    await service.plan_route(_data())
    create_arg = repo.create.call_args[0][0]
    assert create_arg["eta_minutes"] >= 1
    assert create_arg["distance_km"] > 0


async def test_plan_route_with_incidents(svc):
    service, repo, osrm, weights, _, _, calc = svc
    inc = MagicMock()
    inc.location = from_shape(Point(30.52, 50.42), srid=4326)
    inc.severity = "high"
    repo.get_active_incidents_nearby.return_value = [inc]
    repo.get_nearby_segments.return_value = [MagicMock(id=uuid.uuid4())]
    calc.find_path.return_value = None
    osrm.route.return_value = None
    repo.create.return_value = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])

    await service.plan_route(_data())
    weights.mark_incident_zone.assert_awaited()


# ── _publish_ws ───────────────────────────────────────────────

async def test_publish_ws(svc):
    service, _, _, _, _, redis, _ = svc
    await service._publish_ws("inc-1", ["r1"], ["s1"], 50.4, 30.5, "high", "accident")
    assert redis.publish.await_count == 2
    call1 = redis.publish.call_args_list[0]
    assert call1[0][0] == "ws:route-updates"
    call2 = redis.publish.call_args_list[1]
    assert call2[0][0] == "ws:incidents"


# ── _refresh_incident_weights ─────────────────────────────────

async def test_refresh_incident_weights(svc):
    service, repo, _, weights, _, _, _ = svc
    inc = MagicMock()
    inc.location = from_shape(Point(30.5, 50.4), srid=4326)
    inc.severity = "medium"
    seg = MagicMock()
    seg.id = uuid.uuid4()
    repo.get_nearby_segments.return_value = [seg]
    await service._refresh_incident_weights([inc])
    weights.mark_incident_zone.assert_awaited_once()


# ── reroute_affected ──────────────────────────────────────────

async def test_reroute_resolved_clears_weights(svc):
    service, repo, _, weights, _, redis, _ = svc
    seg = MagicMock()
    seg.id = uuid.uuid4()
    repo.get_nearby_segments.return_value = [seg]
    repo.get_routes_through_area.return_value = []
    repo.get_rerouted_routes.return_value = []

    result = await service.reroute_affected(
        "inc-1", ["s1"], 50.4, 30.5, severity="high", action="resolved",
    )
    weights.clear_incident_zone.assert_awaited_once()
    assert result == []


async def test_reroute_no_routes(svc):
    service, repo, _, _, _, redis, _ = svc
    repo.get_nearby_segments.return_value = []
    result = await service.reroute_affected("inc-2", [], 50.4, 30.5)
    assert result == []
    assert redis.publish.await_count == 2


async def test_reroute_with_routes(svc):
    service, repo, osrm, weights, event_bus, redis, calc = svc
    route = _route(
        wp_coords=[(30.5, 50.4), (30.55, 50.45)],
        dist=2.0,
    )
    repo.get_nearby_segments.return_value = []
    repo.get_routes_through_area.return_value = [route]

    pipe = AsyncMock()
    pipe.get = MagicMock()
    pipe.execute = AsyncMock(return_value=[json.dumps({"lat": 50.41, "lng": 30.51})])
    redis.pipeline = MagicMock(return_value=pipe)

    calc.find_path.return_value = _path()
    osrm.match.return_value = _geom()
    updated = _route(
        vid=route.vehicle_id,
        wp_coords=[(30.5, 50.4), (30.52, 50.43), (30.55, 50.45)],
        dist=2.2,
        recount=1,
    )
    repo.update_route.return_value = updated

    result = await service.reroute_affected("inc-3", ["s1"], 50.4, 30.5, severity="medium")
    assert len(result) >= 1
    event_bus.publish.assert_awaited()


async def test_reroute_handles_exception_in_task(svc):
    service, repo, _, _, event_bus, redis, calc = svc
    route = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])
    repo.get_nearby_segments.return_value = []
    repo.get_routes_through_area.return_value = [route]

    pipe = AsyncMock()
    pipe.execute = AsyncMock(return_value=[None])
    redis.pipeline = MagicMock(return_value=pipe)

    calc.find_path.side_effect = RuntimeError("graph broken")

    result = await service.reroute_affected("inc-4", [], 50.4, 30.5)
    assert result == []


# ── _reroute_single ───────────────────────────────────────────

async def test_reroute_single_with_position(svc):
    service, repo, osrm, _, _, _, calc = svc
    route = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)], dist=2.0)
    pos_raw = json.dumps({"lat": 50.41, "lng": 30.51}).encode()

    calc.find_path.return_value = _path()
    osrm.match.return_value = _geom(dist=2100, dur=180)

    updated = _route(recount=1)
    repo.update_route.return_value = updated

    session = AsyncMock()
    result = await service._reroute_single(session, route, pos_raw, {}, "medium")
    assert result is not None
    repo.update_route.assert_awaited_once()


async def test_reroute_single_no_position(svc):
    service, repo, osrm, _, _, _, calc = svc
    route = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)], dist=2.0)
    calc.find_path.return_value = _path()
    osrm.match.return_value = _geom(dist=2100, dur=180)
    repo.update_route.return_value = _route(recount=1)

    result = await service._reroute_single(AsyncMock(), route, None, {}, "medium")
    assert result is not None


async def test_reroute_single_astar_raw(svc):
    service, repo, osrm, _, _, _, calc = svc
    route = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)], dist=2.0)
    calc.find_path.return_value = _path()
    osrm.match.return_value = None
    repo.update_route.return_value = _route(recount=1)

    result = await service._reroute_single(AsyncMock(), route, None, {}, "medium")
    assert result is not None


async def test_reroute_single_osrm_alternatives(svc):
    service, repo, osrm, _, _, _, calc = svc
    route = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)], dist=2.0)
    calc.find_path.return_value = None
    osrm.route_alternatives.return_value = [
        _geom(dist=2200, dur=190),
        _geom(dist=2100, dur=180),
    ]
    repo.update_route.return_value = _route(recount=1)

    result = await service._reroute_single(AsyncMock(), route, None, {}, "medium")
    assert result is not None


async def test_reroute_single_detour_cap_exceeded(svc):
    service, repo, osrm, _, _, _, calc = svc
    route = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)], dist=1.0)
    calc.find_path.return_value = _path(dist_m=10_000)
    osrm.match.return_value = _geom(dist=10_000, dur=600)

    result = await service._reroute_single(AsyncMock(), route, None, {}, "low")
    assert result is None


async def test_reroute_single_nothing_found(svc):
    service, repo, osrm, _, _, _, calc = svc
    route = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)])
    calc.find_path.return_value = None
    osrm.route_alternatives.return_value = []

    result = await service._reroute_single(AsyncMock(), route, None, {}, "medium")
    assert result is None


async def test_reroute_single_pins_distant_endpoint(svc):
    service, repo, osrm, _, _, _, calc = svc
    route = _route(
        dest=(30.60, 50.50),
        wp_coords=[(30.5, 50.4), (30.55, 50.45)],
        dist=5.0,
    )
    calc.find_path.return_value = _path(
        coords=[(30.5, 50.4), (30.55, 50.45), (30.58, 50.48)],
    )
    osrm.match.return_value = _geom(
        waypoints=[(30.5, 50.4), (30.55, 50.45), (30.58, 50.48)],
        dist=5500,
        dur=400,
    )
    repo.update_route.return_value = _route(recount=1)

    result = await service._reroute_single(AsyncMock(), route, None, {}, "high")
    assert result is not None


async def test_reroute_single_zero_duration(svc):
    service, repo, osrm, _, _, _, calc = svc
    route = _route(wp_coords=[(30.5, 50.4), (30.55, 50.45)], dist=2.0)
    calc.find_path.return_value = _path()
    osrm.match.return_value = _geom(dist=2100, dur=0)
    repo.update_route.return_value = _route(recount=1)

    result = await service._reroute_single(AsyncMock(), route, None, {}, "medium")
    assert result is not None
