"""OSMnx-style graph preprocessing configuration.

Defaults match OSMnx 2.x: `drive` filter excludes pedestrian/cycle paths,
10 m consolidation tolerance merges near-duplicate intersection nodes.
KDTree nearest-node lookup (~10 µs/query for 30k nodes) outperforms
PostGIS GiST below ~500k nodes — fall back to PostGIS only for
line-snapping queries that need actual geometry.
"""

GRAPH_NETWORK_TYPE: str = "drive"
GRAPH_CONSOLIDATE_TOLERANCE_M: int = 10
GRAPH_NEAREST_NODE: str = "kdtree"
