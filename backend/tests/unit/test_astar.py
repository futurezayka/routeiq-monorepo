import pytest

from app.modules.route_planning.calculator import (
    RouteCalculator,
    _node_key,
    haversine,
)


def test_haversine_zero_distance():
    assert haversine(50.0, 30.0, 50.0, 30.0) == pytest.approx(0.0)


def test_haversine_known_distance():
    d = haversine(50.45, 30.52, 50.46, 30.52)
    assert 1100 < d < 1120


def test_node_key_deterministic():
    assert _node_key(50.4500001, 30.5200002) == "50.4500001,30.5200002"
    assert _node_key(50.45, 30.52) == _node_key(50.45, 30.52)


def test_trace_path_assembles_coordinates():
    calc = RouteCalculator()
    calc._node_coords = {
        "A": (50.45, 30.50),
        "B": (50.46, 30.51),
        "C": (50.47, 30.52),
    }
    calc._edge_segment_ids = {
        ("A", "B"): "seg1",
        ("B", "C"): "seg2",
    }
    calc._edge_geometries = {
        "seg1": [(30.50, 50.45), (30.505, 50.455), (30.51, 50.46)],
        "seg2": [(30.51, 50.46), (30.515, 50.465), (30.52, 50.47)],
    }
    calc._edge_info = {
        "seg1": (1200.0, 60),
        "seg2": (1300.0, 50),
    }

    weights = {"seg1": 1.0, "seg2": 1.0}
    coords, seg_ids, dist_m, time_s = calc._trace_path(
        ["A", "B", "C"], weights,
    )

    assert seg_ids == ["seg1", "seg2"]
    assert dist_m == pytest.approx(2500.0)
    assert len(coords) >= 4


def test_trace_path_with_weights_affects_eta():
    calc = RouteCalculator()
    calc._node_coords = {
        "A": (50.45, 30.50),
        "B": (50.46, 30.51),
    }
    calc._edge_segment_ids = {("A", "B"): "seg1"}
    calc._edge_geometries = {
        "seg1": [(30.50, 50.45), (30.51, 50.46)],
    }
    calc._edge_info = {"seg1": (1000.0, 60)}

    _, _, _, time_normal = calc._trace_path(["A", "B"], {"seg1": 1.0})
    _, _, _, time_weighted = calc._trace_path(["A", "B"], {"seg1": 4.0})

    assert time_weighted == pytest.approx(time_normal * 4.0)
