"""NetworkX-based A* route calculator with PostGIS KNN nearest-node lookup.

Graph is loaded once from all road_segments and cached in-process.
Dynamic edge weights (incident / congestion / weather) come from Redis
via GraphWeightManager — fetched fresh per routing request.
"""

import asyncio
import logging
import math

import networkx as nx
import numpy as np
from geoalchemy2.shape import to_shape
from shapely import STRtree
from shapely.geometry import LineString, Point
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.route_planning.graph_weights import GraphWeightManager
from app.modules.route_planning.polyline_config import DP_TOLERANCE_DEG

logger = logging.getLogger(__name__)

MAX_SPEED_MS = 33.33  # 120 km/h — used in A* heuristic (admissible lower bound)

# Highway classes where reverse traversal is structurally impossible
# (motorway carriageways + slip-road on/off-ramps). Without this filter, A*
# can produce zigzags where it briefly traverses a ramp in the wrong
# direction to reach a closer node.


_EARTH_R_M = 6_371_000.0


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Scalar haversine — math.* beats numpy for single-point calls."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return _EARTH_R_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def haversine_batch(
    lat1: np.ndarray, lng1: np.ndarray, lat2: np.ndarray, lng2: np.ndarray,
) -> np.ndarray:
    """Vectorised haversine for paired arrays — used when computing many
    distances at once (e.g. graph diagnostics, polyline distance)."""
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lng2 - lng1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return _EARTH_R_M * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))


def _node_key(lat: float, lng: float) -> str:
    return f"{lat:.7f},{lng:.7f}"


class PathResult:
    __slots__ = ("coords", "segment_ids", "distance_m", "eta_minutes")

    def __init__(
        self,
        coords: list[tuple[float, float]],
        segment_ids: list[str],
        distance_m: float,
        eta_minutes: int,
    ) -> None:
        self.coords = coords
        self.segment_ids = segment_ids
        self.distance_m = distance_m
        self.eta_minutes = eta_minutes


_KNN_SQL = text(
    "SELECT start_node_id, end_node_id,"
    " ST_Y(ST_StartPoint(geometry)) AS s_lat,"
    " ST_X(ST_StartPoint(geometry)) AS s_lng,"
    " ST_Y(ST_EndPoint(geometry)) AS e_lat,"
    " ST_X(ST_EndPoint(geometry)) AS e_lng"
    " FROM road_segments"
    " ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)"
    " LIMIT 1"
)


class RouteCalculator:
    """Singleton graph holder. Build once from all road_segments, reuse."""

    def __init__(self) -> None:
        self._graph: nx.DiGraph | None = None
        self._node_coords: dict[str, tuple[float, float]] = {}
        self._edge_segment_ids: dict[tuple[str, str], str] = {}
        self._edge_geometries: dict[str, list[tuple[float, float]]] = {}
        self._edge_info: dict[str, tuple[float, int]] = {}
        self._all_segment_ids: list[str] = []
        self._node_index: STRtree | None = None
        self._node_index_ids: list[str] = []
        self._node_coords_array: np.ndarray | None = None
        self._lock = asyncio.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._graph is not None

    async def ensure_graph(self, session: AsyncSession) -> None:
        if self._graph is not None:
            return
        async with self._lock:
            if self._graph is not None:
                return
            await self._build_graph(session)

    async def _build_graph(self, session: AsyncSession) -> None:
        from app.models.road_segment import RoadSegment

        result = await session.execute(select(RoadSegment))
        segments = list(result.scalars().all())
        if not segments:
            logger.warning("No road segments — graph empty")
            self._graph = nx.DiGraph()
            return

        G = nx.DiGraph()
        seen_sids: set[str] = set()
        oneway_count = 0

        for seg in segments:
            shape = to_shape(seg.geometry)
            c = list(shape.coords)
            s_lng, s_lat = c[0][0], c[0][1]
            e_lng, e_lat = c[-1][0], c[-1][1]

            sk = seg.start_node_id or _node_key(s_lat, s_lng)
            ek = seg.end_node_id or _node_key(e_lat, e_lng)

            self._node_coords[sk] = (s_lat, s_lng)
            self._node_coords[ek] = (e_lat, e_lng)

            length = seg.length_m or haversine(s_lat, s_lng, e_lat, e_lng)
            sid = str(seg.id)
            speed_limit = seg.speed_limit or 40
            speed_ms = max(speed_limit, 5) * 1000 / 3600
            base_cost = length / speed_ms
            road_type = (seg.road_type or "unclassified").lower()

            G.add_edge(sk, ek, segment_id=sid, base_cost=base_cost)
            self._edge_segment_ids[(sk, ek)] = sid

            if not seg.oneway:
                G.add_edge(ek, sk, segment_id=sid, base_cost=base_cost)
                self._edge_segment_ids[(ek, sk)] = sid
            else:
                oneway_count += 1

            self._edge_geometries[sid] = c
            self._edge_info[sid] = (length, speed_limit)
            seen_sids.add(sid)

        self._all_segment_ids = list(seen_sids)
        self._graph = G

        # Spatial index for O(log n) nearest-node lookup — replaces a
        # PostGIS KNN round-trip (~1–3 ms) with an in-process GEOS query
        # (~10 µs). Falls back to PostGIS if the index is empty.
        node_ids = list(self._node_coords.keys())
        if node_ids:
            arr = np.fromiter(
                (
                    coord
                    for nid in node_ids
                    for coord in self._node_coords[nid]
                ),
                dtype=np.float64,
                count=2 * len(node_ids),
            ).reshape(-1, 2)
            self._node_coords_array = arr
            points = [Point(lng, lat) for lat, lng in arr]
            self._node_index = STRtree(points)
            self._node_index_ids = node_ids

        logger.info(
            "Road graph: %d nodes, %d edges (%d segments, %d one-way), STRtree=%s",
            G.number_of_nodes(), G.number_of_edges(), len(segments),
            oneway_count,
            "yes" if self._node_index is not None else "no",
        )

    async def fetch_weights(
        self, weight_manager: GraphWeightManager,
    ) -> dict[str, float]:
        return await weight_manager.get_weights_batch(self._all_segment_ids)

    async def nearest_node(
        self, session: AsyncSession, lat: float, lng: float,
    ) -> str | None:
        if self._node_index is not None and self._node_index_ids:
            idx = self._node_index.nearest(Point(lng, lat))
            if idx is not None:
                return self._node_index_ids[int(idx)]

        # Fallback: PostGIS KNN against road_segments
        result = await session.execute(_KNN_SQL, {"lat": lat, "lng": lng})
        row = result.first()
        if not row:
            return None
        sk = row.start_node_id or _node_key(row.s_lat, row.s_lng)
        ek = row.end_node_id or _node_key(row.e_lat, row.e_lng)
        d_start = haversine(lat, lng, row.s_lat, row.s_lng)
        d_end = haversine(lat, lng, row.e_lat, row.e_lng)
        return sk if d_start <= d_end else ek

    async def find_path(
        self,
        session: AsyncSession,
        o_lat: float,
        o_lng: float,
        d_lat: float,
        d_lng: float,
        weights: dict[str, float],
    ) -> PathResult | None:
        await self.ensure_graph(session)
        if self._graph is None or self._graph.number_of_nodes() == 0:
            return None

        ok = await self.nearest_node(session, o_lat, o_lng)
        dk = await self.nearest_node(session, d_lat, d_lng)
        if not ok or not dk or ok == dk:
            return None
        if ok not in self._graph or dk not in self._graph:
            return None

        node_coords = self._node_coords

        def weight_fn(u, v, d):
            return d["base_cost"] * weights.get(d["segment_id"], 1.0)

        def heuristic(u, v):
            c1 = node_coords.get(u)
            c2 = node_coords.get(v)
            if not c1 or not c2:
                return 0.0
            return haversine(c1[0], c1[1], c2[0], c2[1]) / MAX_SPEED_MS

        try:
            path = nx.astar_path(
                self._graph, ok, dk,
                heuristic=heuristic,
                weight=weight_fn,
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

        coords, segment_ids, total_dist_m, total_time_s = self._trace_path(
            path, weights,
        )
        if len(coords) < 2:
            return None

        # Douglas-Peucker smoothing — coalesces micro-jitters that appear
        # when an A* path threads many short segments / consolidated
        # intersection nodes (V-spikes, rectangular stair-steps near
        # boulevards). Distance/ETA come from edge physics, so vertex
        # reduction does NOT alter them.
        if len(coords) > 15:
            simplified = LineString(coords).simplify(
                DP_TOLERANCE_DEG, preserve_topology=False,
            )
            new_coords: list[tuple[float, float]] = [
                (x, y) for x, y in simplified.coords
            ]
            if len(new_coords) >= 5:
                logger.debug(
                    "DP simplified: %d → %d waypoints (route %.2fkm)",
                    len(coords), len(new_coords), total_dist_m / 1000,
                )
                coords = new_coords

        return PathResult(
            coords=coords,
            segment_ids=segment_ids,
            distance_m=total_dist_m,
            eta_minutes=max(1, round(total_time_s / 60)),
        )

    def _trace_path(
        self,
        path: list[str],
        weights: dict[str, float],
    ) -> tuple[list[tuple[float, float]], list[str], float, float]:
        coords: list[tuple[float, float]] = []
        segment_ids: list[str] = []
        total_dist_m = 0.0
        total_time_s = 0.0

        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            sid = self._edge_segment_ids.get((u, v))
            if not sid:
                continue
            segment_ids.append(sid)
            length_m, speed_limit = self._edge_info.get(sid, (0, 40))
            total_dist_m += length_m
            speed_ms = max(speed_limit, 5) * 1000 / 3600
            total_time_s += (length_m / speed_ms) * weights.get(sid, 1.0)

            geom = self._edge_geometries.get(sid)
            if not geom:
                continue
            u_lat, u_lng = self._node_coords[u]
            geom_s_lat, geom_s_lng = geom[0][1], geom[0][0]
            if haversine(u_lat, u_lng, geom_s_lat, geom_s_lng) < 10.0:
                seg_coords = list(geom)
            else:
                seg_coords = list(reversed(geom))
            if coords and seg_coords:
                last = coords[-1]
                first = seg_coords[0]
                if haversine(last[1], last[0], first[1], first[0]) < 15.0:
                    seg_coords = seg_coords[1:]
            coords.extend(seg_coords)

        if not coords and path:
            c = self._node_coords.get(path[0])
            if c:
                coords.append((c[1], c[0]))
        if path:
            c = self._node_coords.get(path[-1])
            if c:
                last_coord = (c[1], c[0])
                if not coords or coords[-1] != last_coord:
                    coords.append(last_coord)

        return coords, segment_ids, total_dist_m, total_time_s
