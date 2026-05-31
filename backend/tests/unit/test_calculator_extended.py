"""Extended unit tests for RouteCalculator — covers build, find_path, nearest_node."""

from unittest.mock import AsyncMock, MagicMock, patch

import networkx as nx
import numpy as np
import pytest
from shapely.geometry import LineString

from app.modules.route_planning.calculator import (
    PathResult,
    RouteCalculator,
    _node_key,
    haversine,
    haversine_batch,
)


# ── haversine_batch ──────────────────────────────────────────

def test_batch_matches_scalar():
    lat1 = np.array([50.45])
    lng1 = np.array([30.52])
    lat2 = np.array([50.46])
    lng2 = np.array([30.53])
    result = haversine_batch(lat1, lng1, lat2, lng2)
    np.testing.assert_allclose(result[0], haversine(50.45, 30.52, 50.46, 30.53), rtol=1e-6)


def test_batch_multiple_pairs():
    n = 50
    result = haversine_batch(
        np.full(n, 50.0), np.full(n, 30.0),
        np.linspace(50.0, 50.1, n), np.linspace(30.0, 30.1, n),
    )
    assert result.shape == (n,)
    assert result[0] == pytest.approx(0.0, abs=1.0)
    assert result[-1] > 0


def test_batch_same_points_zero():
    lat = np.array([50.0, 51.0])
    lng = np.array([30.0, 31.0])
    np.testing.assert_allclose(haversine_batch(lat, lng, lat, lng), 0.0, atol=1e-10)


# ── PathResult ────────────────────────────────────────────────

def test_path_result_slots():
    pr = PathResult(
        coords=[(30.5, 50.4), (30.6, 50.5)],
        segment_ids=["s1"],
        distance_m=1000.0,
        eta_minutes=5,
    )
    assert pr.coords == [(30.5, 50.4), (30.6, 50.5)]
    assert pr.segment_ids == ["s1"]
    assert pr.distance_m == 1000.0
    assert pr.eta_minutes == 5


# ── is_loaded ─────────────────────────────────────────────────

def test_not_loaded_initially():
    assert not RouteCalculator().is_loaded


def test_loaded_after_graph_set():
    calc = RouteCalculator()
    calc._graph = nx.DiGraph()
    assert calc.is_loaded


# ── ensure_graph ──────────────────────────────────────────────

async def test_ensure_graph_skips_if_loaded():
    calc = RouteCalculator()
    calc._graph = nx.DiGraph()
    session = AsyncMock()
    await calc.ensure_graph(session)
    session.execute.assert_not_awaited()


async def test_ensure_graph_builds_empty():
    calc = RouteCalculator()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_mock)
    await calc.ensure_graph(session)
    assert calc._graph is not None
    assert calc._graph.number_of_nodes() == 0


# ── _build_graph ──────────────────────────────────────────────

def _seg(sid, start_id, end_id, coords, oneway=False, speed=60, length=None, road_type="primary"):
    seg = MagicMock()
    seg.id = sid
    seg.start_node_id = start_id
    seg.end_node_id = end_id
    seg.length_m = length
    seg.speed_limit = speed
    seg.oneway = oneway
    seg.road_type = road_type
    seg._coords = coords
    return seg


async def test_build_graph_bidirectional():
    calc = RouteCalculator()
    s = _seg("s1", "n1", "n2", [(30.5, 50.4), (30.51, 50.41)])
    line = LineString(s._coords)
    with patch("app.modules.route_planning.calculator.to_shape", return_value=line):
        rm = MagicMock()
        rm.scalars.return_value.all.return_value = [s]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=rm)
        await calc._build_graph(session)
    assert calc._graph.has_edge("n1", "n2")
    assert calc._graph.has_edge("n2", "n1")
    assert "s1" in calc._all_segment_ids
    assert calc._node_index is not None


async def test_build_graph_oneway():
    calc = RouteCalculator()
    s = _seg("s-ow", "a", "b", [(30.5, 50.4), (30.51, 50.41)], oneway=True)
    line = LineString(s._coords)
    with patch("app.modules.route_planning.calculator.to_shape", return_value=line):
        rm = MagicMock()
        rm.scalars.return_value.all.return_value = [s]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=rm)
        await calc._build_graph(session)
    assert calc._graph.has_edge("a", "b")
    assert not calc._graph.has_edge("b", "a")


async def test_build_graph_auto_node_keys():
    calc = RouteCalculator()
    s = _seg("s-gen", None, None, [(30.5, 50.4), (30.6, 50.5)])
    line = LineString(s._coords)
    with patch("app.modules.route_planning.calculator.to_shape", return_value=line):
        rm = MagicMock()
        rm.scalars.return_value.all.return_value = [s]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=rm)
        await calc._build_graph(session)
    assert calc._graph.number_of_nodes() == 2
    assert all("," in k for k in calc._node_coords)


async def test_build_graph_defaults():
    calc = RouteCalculator()
    s = _seg("s-def", "x", "y", [(30.5, 50.4), (30.6, 50.5)], speed=None, length=None, road_type=None)
    line = LineString(s._coords)
    with patch("app.modules.route_planning.calculator.to_shape", return_value=line):
        rm = MagicMock()
        rm.scalars.return_value.all.return_value = [s]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=rm)
        await calc._build_graph(session)
    assert calc._graph.has_edge("x", "y")


# ── fetch_weights ─────────────────────────────────────────────

async def test_fetch_weights_delegates():
    calc = RouteCalculator()
    calc._all_segment_ids = ["s1", "s2"]
    wm = AsyncMock()
    wm.get_weights_batch = AsyncMock(return_value={"s1": 1.0, "s2": 2.0})
    assert await calc.fetch_weights(wm) == {"s1": 1.0, "s2": 2.0}


# ── nearest_node ──────────────────────────────────────────────

async def test_nearest_node_strtree():
    calc = RouteCalculator()
    calc._node_coords = {"n1": (50.4, 30.5), "n2": (50.5, 30.6)}
    calc._node_index_ids = ["n1", "n2"]
    calc._node_index = MagicMock()
    calc._node_index.nearest.return_value = 0
    assert await calc.nearest_node(AsyncMock(), 50.4, 30.5) == "n1"


async def test_nearest_node_postgis_fallback():
    calc = RouteCalculator()
    calc._node_index = None
    calc._node_index_ids = []
    row = MagicMock()
    row.start_node_id = "pg_s"
    row.end_node_id = "pg_e"
    row.s_lat, row.s_lng = 50.4, 30.5
    row.e_lat, row.e_lng = 50.41, 30.51
    rm = MagicMock()
    rm.first.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=rm)
    assert await calc.nearest_node(session, 50.4, 30.5) == "pg_s"


async def test_nearest_node_postgis_picks_closer_end():
    calc = RouteCalculator()
    calc._node_index = None
    calc._node_index_ids = []
    row = MagicMock()
    row.start_node_id = "s"
    row.end_node_id = "e"
    row.s_lat, row.s_lng = 50.0, 30.0
    row.e_lat, row.e_lng = 50.41, 30.51
    rm = MagicMock()
    rm.first.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=rm)
    assert await calc.nearest_node(session, 50.41, 30.51) == "e"


async def test_nearest_node_postgis_none():
    calc = RouteCalculator()
    calc._node_index = None
    calc._node_index_ids = []
    rm = MagicMock()
    rm.first.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=rm)
    assert await calc.nearest_node(session, 50.4, 30.5) is None


# ── find_path ─────────────────────────────────────────────────

async def test_find_path_no_graph():
    calc = RouteCalculator()
    calc._graph = None
    rm = MagicMock()
    rm.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=rm)
    assert await calc.find_path(session, 50.4, 30.5, 50.5, 30.6, {}) is None


async def test_find_path_empty_graph():
    calc = RouteCalculator()
    calc._graph = nx.DiGraph()
    assert await calc.find_path(AsyncMock(), 50.4, 30.5, 50.5, 30.6, {}) is None


async def test_find_path_same_node():
    calc = RouteCalculator()
    calc._graph = nx.DiGraph()
    calc._graph.add_node("n1")
    calc._node_coords = {"n1": (50.4, 30.5)}
    calc._node_index_ids = ["n1"]
    calc._node_index = MagicMock()
    calc._node_index.nearest.return_value = 0
    assert await calc.find_path(AsyncMock(), 50.4, 30.5, 50.4, 30.5, {}) is None


async def test_find_path_no_path_exists():
    calc = RouteCalculator()
    G = nx.DiGraph()
    G.add_node("n1")
    G.add_node("n2")
    calc._graph = G
    calc._node_coords = {"n1": (50.4, 30.5), "n2": (50.5, 30.6)}
    calc._node_index_ids = ["n1", "n2"]
    calc._node_index = MagicMock()
    calc._node_index.nearest.side_effect = [0, 1]
    calc._edge_segment_ids = {}
    calc._edge_info = {}
    calc._edge_geometries = {}
    assert await calc.find_path(AsyncMock(), 50.4, 30.5, 50.5, 30.6, {}) is None


# ── _trace_path edge cases ────────────────────────────────────

def test_trace_path_empty():
    calc = RouteCalculator()
    calc._node_coords = {}
    coords, sids, d, t = calc._trace_path([], {})
    assert coords == []
    assert sids == []


def test_trace_path_single_node():
    calc = RouteCalculator()
    calc._node_coords = {"n1": (50.4, 30.5)}
    calc._edge_segment_ids = {}
    calc._edge_info = {}
    calc._edge_geometries = {}
    coords, sids, d, t = calc._trace_path(["n1"], {})
    assert len(coords) >= 1


def test_trace_path_missing_edge():
    calc = RouteCalculator()
    calc._node_coords = {"n1": (50.4, 30.5), "n2": (50.5, 30.6)}
    calc._edge_segment_ids = {}
    calc._edge_info = {}
    calc._edge_geometries = {}
    coords, sids, d, t = calc._trace_path(["n1", "n2"], {})
    assert len(sids) == 0
    assert len(coords) >= 1


def test_trace_path_reversed_geometry():
    calc = RouteCalculator()
    calc._node_coords = {"n1": (50.4, 30.5), "n2": (50.41, 30.51)}
    calc._edge_segment_ids = {("n1", "n2"): "s1"}
    calc._edge_info = {"s1": (500.0, 60)}
    calc._edge_geometries = {"s1": [(30.51, 50.41), (30.5, 50.4)]}
    coords, sids, d, t = calc._trace_path(["n1", "n2"], {})
    assert "s1" in sids
    assert d == 500.0
