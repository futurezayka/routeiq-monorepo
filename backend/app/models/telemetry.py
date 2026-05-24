import uuid
from datetime import datetime

from sqlalchemy import REAL, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Telemetry(Base):
    __tablename__ = "telemetry"
    __table_args__ = (
        {"postgresql_partition_by": "RANGE (time)"},
    )

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vehicles.id"),
        primary_key=True,
    )
    latitude: Mapped[float] = mapped_column(Float(precision=53), nullable=False)
    longitude: Mapped[float] = mapped_column(Float(precision=53), nullable=False)
    speed_kmh: Mapped[float | None] = mapped_column(REAL)
    heading: Mapped[float | None] = mapped_column(REAL)
    road_segment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("road_segments.id"),
        nullable=True,
    )
