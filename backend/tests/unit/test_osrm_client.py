"""Unit tests for OSRM client — all HTTP calls mocked."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.modules.route_planning.osrm_client import (
    NearestPoint,
    OSRMClient,
    RouteGeometry,
    _dist_m,
    _remove_spurs,
)


# ── helpers ──────────────────────────────────────────────────

def _resp(json_data):
    r = MagicMock()
    r.json.return_value = json_data
    r.raise_for_status = MagicMock()
    return r


def _http(response=None, side_effect=None):
    c = MagicMock()
    if side_effect:
        c.get = AsyncMock(side_effect=side_effect)
    else:
        c.get = AsyncMock(return_value=response)
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=False)
    return c


def _patch_httpx(mock_client):
    return patch(
        "app.modules.route_planning.osrm_client.httpx.AsyncClient",
        return_value=mock_client,
    )


_ROUTE_OK = {
    "code": "Ok",
    "routes": [{
        "geometry": {"coordinates": [[30.5, 50.4], [30.51, 50.41], [30.52, 50.42]]},
        "distance": 1500.0,
        "duration": 120.0,
    }],
}


# ── pure helpers ─────────────────────────────────────────────

def test_dist_m_same_point():
    assert _dist_m((30.0, 50.0), (30.0, 50.0)) == 0.0


def test_dist_m_known_lng():
    d = _dist_m((30.0, 50.0), (31.0, 50.0))
    assert 70_000 < d < 73_000


def test_dist_m_known_lat():
    d = _dist_m((30.0, 50.0), (30.0, 51.0))
    assert 110_000 < d < 112_000


def test_remove_spurs_passthrough():
    pts = [(0.0, 0.0), (0.001, 0.0), (0.002, 0.0)]
    assert _remove_spurs(pts) == pts


def test_remove_spurs_empty():
    assert _remove_spurs([]) == []


def test_remove_spurs_single():
    assert _remove_spurs([(5.0, 5.0)]) == [(5.0, 5.0)]


def test_remove_spurs_detects_spur():
    pts = [(30.0, 50.0), (30.0001, 50.0001), (30.0, 50.0), (30.001, 50.0)]
    result = _remove_spurs(pts, close_threshold_m=60.0)
    assert len(result) <= len(pts)


# ── OSRMClient.route ────────────────────────────────────────

@pytest.fixture
def osrm():
    return OSRMClient(base_url="http://osrm-test:5000")


async def test_route_success(osrm):
    with _patch_httpx(_http(_resp(_ROUTE_OK))):
        result = await osrm.route((30.5, 50.4), (30.52, 50.42))
    assert isinstance(result, RouteGeometry)
    assert result.distance_m == 1500.0
    assert result.duration_s == 120.0
    assert len(result.waypoints) >= 2


async def test_route_not_ok_code(osrm):
    with _patch_httpx(_http(_resp({"code": "NoRoute"}))):
        assert await osrm.route((30.5, 50.4), (30.52, 50.42)) is None


async def test_route_retries_on_http_error(osrm):
    mock = _http(side_effect=httpx.ConnectError("fail"))
    with _patch_httpx(mock):
        with patch("app.modules.route_planning.osrm_client.asyncio.sleep", new_callable=AsyncMock):
            result = await osrm.route((30.5, 50.4), (30.52, 50.42))
    assert result is None
    assert mock.get.call_count == 3


async def test_route_retries_then_succeeds(osrm):
    effects = [httpx.ConnectError("fail"), _resp(_ROUTE_OK)]
    mock = _http(side_effect=effects)
    with _patch_httpx(mock):
        with patch("app.modules.route_planning.osrm_client.asyncio.sleep", new_callable=AsyncMock):
            result = await osrm.route((30.5, 50.4), (30.52, 50.42))
    assert result is not None
    assert result.distance_m == 1500.0


async def test_route_key_error_retries(osrm):
    bad_data = {"code": "Ok", "routes": [{"geometry": {}}]}
    mock = _http(side_effect=[KeyError("coordinates"), _resp(_ROUTE_OK)])
    with _patch_httpx(mock):
        with patch("app.modules.route_planning.osrm_client.asyncio.sleep", new_callable=AsyncMock):
            result = await osrm.route((30.5, 50.4), (30.52, 50.42))
    assert result is not None


# ── OSRMClient.route_alternatives ────────────────────────────

async def test_route_alternatives_success(osrm):
    data = {
        "code": "Ok",
        "routes": [
            {"geometry": {"coordinates": [[30.5, 50.4], [30.52, 50.42]]}, "distance": 1000, "duration": 80},
            {"geometry": {"coordinates": [[30.5, 50.4], [30.51, 50.41], [30.52, 50.42]]}, "distance": 1200, "duration": 100},
        ],
    }
    with _patch_httpx(_http(_resp(data))):
        result = await osrm.route_alternatives((30.5, 50.4), (30.52, 50.42), 3)
    assert len(result) == 2
    assert result[0].distance_m == 1000


async def test_route_alternatives_not_ok(osrm):
    with _patch_httpx(_http(_resp({"code": "NoRoute"}))):
        assert await osrm.route_alternatives((30.5, 50.4), (30.52, 50.42)) == []


async def test_route_alternatives_http_error(osrm):
    with _patch_httpx(_http(side_effect=httpx.ConnectError("fail"))):
        assert await osrm.route_alternatives((30.5, 50.4), (30.52, 50.42)) == []


# ── OSRMClient.route_via ─────────────────────────────────────

async def test_route_via_success(osrm):
    with _patch_httpx(_http(_resp(_ROUTE_OK))):
        result = await osrm.route_via((30.5, 50.4), [(30.51, 50.41)], (30.52, 50.42))
    assert result is not None
    assert result.distance_m == 1500.0


async def test_route_via_not_ok(osrm):
    with _patch_httpx(_http(_resp({"code": "NoRoute"}))):
        assert await osrm.route_via((30.5, 50.4), [(30.51, 50.41)], (30.52, 50.42)) is None


async def test_route_via_retries_on_error(osrm):
    mock = _http(side_effect=httpx.ConnectError("fail"))
    with _patch_httpx(mock):
        with patch("app.modules.route_planning.osrm_client.asyncio.sleep", new_callable=AsyncMock):
            assert await osrm.route_via((30.5, 50.4), [], (30.52, 50.42)) is None
    assert mock.get.call_count == 3


# ── OSRMClient.match ─────────────────────────────────────────

async def test_match_success(osrm):
    data = {
        "code": "Ok",
        "matchings": [{
            "geometry": {"coordinates": [[30.5, 50.4], [30.51, 50.41], [30.52, 50.42]]},
            "distance": 1400.0,
            "duration": 110.0,
        }],
    }
    coords = [(30.5, 50.4), (30.51, 50.41), (30.52, 50.42)]
    with _patch_httpx(_http(_resp(data))):
        result = await osrm.match(coords)
    assert result is not None
    assert result.distance_m == 1400.0


async def test_match_multiple_matchings(osrm):
    data = {
        "code": "Ok",
        "matchings": [
            {"geometry": {"coordinates": [[30.5, 50.4], [30.51, 50.41]]}, "distance": 700, "duration": 55},
            {"geometry": {"coordinates": [[30.51, 50.41], [30.52, 50.42]]}, "distance": 700, "duration": 55},
        ],
    }
    with _patch_httpx(_http(_resp(data))):
        result = await osrm.match([(30.5, 50.4), (30.51, 50.41), (30.52, 50.42)])
    assert result is not None
    assert result.distance_m == 1400.0
    assert result.duration_s == 110.0


async def test_match_too_few_coords(osrm):
    assert await osrm.match([(30.5, 50.4)]) is None


async def test_match_samples_over_100(osrm):
    data = {
        "code": "Ok",
        "matchings": [{
            "geometry": {"coordinates": [[30.0, 50.0], [30.15, 50.15]]},
            "distance": 10000, "duration": 800,
        }],
    }
    coords = [(30.0 + i * 0.001, 50.0 + i * 0.001) for i in range(150)]
    mock = _http(_resp(data))
    with _patch_httpx(mock):
        result = await osrm.match(coords)
    assert result is not None
    url_arg = mock.get.call_args[0][0]
    assert url_arg.count(";") == 99


async def test_match_not_ok(osrm):
    with _patch_httpx(_http(_resp({"code": "NoMatch"}))):
        assert await osrm.match([(30.5, 50.4), (30.51, 50.41)]) is None


async def test_match_no_matchings(osrm):
    with _patch_httpx(_http(_resp({"code": "Ok", "matchings": []}))):
        assert await osrm.match([(30.5, 50.4), (30.51, 50.41)]) is None


async def test_match_single_coord_result(osrm):
    data = {
        "code": "Ok",
        "matchings": [{"geometry": {"coordinates": [[30.5, 50.4]]}, "distance": 0, "duration": 0}],
    }
    with _patch_httpx(_http(_resp(data))):
        assert await osrm.match([(30.5, 50.4), (30.51, 50.41)]) is None


async def test_match_retries_on_error(osrm):
    mock = _http(side_effect=httpx.ConnectError("fail"))
    with _patch_httpx(mock):
        with patch("app.modules.route_planning.osrm_client.asyncio.sleep", new_callable=AsyncMock):
            assert await osrm.match([(30.5, 50.4), (30.51, 50.41)]) is None
    assert mock.get.call_count == 3


# ── OSRMClient.nearest ───────────────────────────────────────

async def test_nearest_success(osrm):
    data = {
        "code": "Ok",
        "waypoints": [{"location": [30.51, 50.41], "distance": 15.3}],
    }
    with _patch_httpx(_http(_resp(data))):
        result = await osrm.nearest(50.4, 30.5)
    assert isinstance(result, NearestPoint)
    assert result.latitude == 50.41
    assert result.longitude == 30.51
    assert result.distance_m == 15.3


async def test_nearest_not_ok(osrm):
    with _patch_httpx(_http(_resp({"code": "NoSegment"}))):
        assert await osrm.nearest(50.4, 30.5) is None


async def test_nearest_http_error(osrm):
    with _patch_httpx(_http(side_effect=httpx.ConnectError("fail"))):
        assert await osrm.nearest(50.4, 30.5) is None


# ── OSRMClient.table ─────────────────────────────────────────

async def test_table_success(osrm):
    data = {"code": "Ok", "durations": [[0, 120], [120, 0]]}
    with _patch_httpx(_http(_resp(data))):
        result = await osrm.table([(30.5, 50.4)], [(30.52, 50.42)])
    assert result == [[0, 120], [120, 0]]


async def test_table_not_ok(osrm):
    with _patch_httpx(_http(_resp({"code": "NoTable"}))):
        assert await osrm.table([(30.5, 50.4)], [(30.52, 50.42)]) is None


async def test_table_http_error(osrm):
    with _patch_httpx(_http(side_effect=httpx.ConnectError("fail"))):
        assert await osrm.table([(30.5, 50.4)], [(30.52, 50.42)]) is None
