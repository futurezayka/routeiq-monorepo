"""Seed Kyiv road network from OpenStreetMap into road_segments table."""

import asyncio
import logging

import osmnx as ox
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString
from sqlalchemy import delete, text

from app.core.database import async_session_factory
from app.models.road_segment import RoadSegment
from app.models.traffic_prediction import TrafficPrediction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KYIV_BBOX = {
    "north": 50.59,
    "south": 50.36,
    "east": 30.83,
    "west": 30.30,
}

HIGHWAY_DEFAULT_SPEEDS = {
    "motorway": 110,
    "motorway_link": 60,
    "trunk": 90,
    "trunk_link": 50,
    "primary": 70,
    "primary_link": 50,
    "secondary": 55,
    "secondary_link": 40,
    "tertiary": 45,
    "tertiary_link": 35,
    "unclassified": 35,
    "residential": 30,
    "living_street": 15,
    "service": 20,
}


def normalize_highway(value, default="unclassified"):
    if value is None:
        return default
    if isinstance(value, list):
        return value[0]
    return str(value)


def normalize_maxspeed(value, highway: str = "unclassified"):
    fallback = HIGHWAY_DEFAULT_SPEEDS.get(highway, 40)
    if value is None:
        return fallback
    if isinstance(value, list):
        value = value[0]
    try:
        return int(str(value).split()[0])
    except (ValueError, TypeError, IndexError):
        return fallback


def parse_oneway(value) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        value = value[0]
    s = str(value).lower().strip()
    return s in ("yes", "true", "1", "-1", "reverse")


async def seed():
    logger.info("Downloading Kyiv road network from OSM (may take 2-3 minutes)...")
    G = ox.graph_from_bbox(
        bbox=(
            KYIV_BBOX["west"],
            KYIV_BBOX["south"],
            KYIV_BBOX["east"],
            KYIV_BBOX["north"],
        ),
        network_type="drive",
        simplify=True,
        retain_all=False,
    )
    logger.info("Downloaded %s nodes, %s edges", len(G.nodes), len(G.edges))

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(TrafficPrediction))
            await session.execute(delete(RoadSegment))
        logger.info("Cleared old predictions and segments")

        batch = []
        total = 0
        for u, v, data in G.edges(data=True):
            start_node = G.nodes[u]
            end_node = G.nodes[v]

            if "geometry" in data:
                coords = list(data["geometry"].coords)
            else:
                coords = [
                    (start_node["x"], start_node["y"]),
                    (end_node["x"], end_node["y"]),
                ]
            geom = LineString(coords)

            highway = normalize_highway(data.get("highway"))
            segment = RoadSegment(
                osm_way_id=data.get("osmid") if not isinstance(data.get("osmid"), list) else data["osmid"][0],
                start_node_id=str(u),
                end_node_id=str(v),
                geometry=from_shape(geom, srid=4326),
                length_m=float(data.get("length", 0)),
                speed_limit=normalize_maxspeed(data.get("maxspeed"), highway),
                road_type=highway,
                name=data.get("name") if isinstance(data.get("name"), str) else None,
                oneway=parse_oneway(data.get("oneway")),
            )
            batch.append(segment)

            if len(batch) >= 2000:
                async with async_session_factory() as s2:
                    async with s2.begin():
                        s2.add_all(batch)
                total += len(batch)
                logger.info("  Inserted %s segments...", total)
                batch = []

        if batch:
            async with async_session_factory() as s2:
                async with s2.begin():
                    s2.add_all(batch)
            total += len(batch)

    logger.info("Seeded %s road segments", total)


if __name__ == "__main__":
    asyncio.run(seed())
