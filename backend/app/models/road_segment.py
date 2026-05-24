from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import REAL, BigInteger, Boolean, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class RoadSegment(UUIDMixin, Base):
    __tablename__ = "road_segments"

    osm_way_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    start_node_id: Mapped[str | None] = mapped_column(String(30), index=True)
    end_node_id: Mapped[str | None] = mapped_column(String(30), index=True)
    geometry: Mapped[Any] = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    road_type: Mapped[str | None] = mapped_column(String(50))
    speed_limit: Mapped[int | None] = mapped_column(Integer)
    length_m: Mapped[float | None] = mapped_column(REAL)
    lanes: Mapped[int | None] = mapped_column(SmallInteger)
    oneway: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False,
    )
