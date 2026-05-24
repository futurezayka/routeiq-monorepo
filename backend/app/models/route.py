import uuid
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geometry
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle


class Route(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "routes"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    status: Mapped[str] = mapped_column(
        SAEnum("active", "completed", "cancelled", name="route_status"),
        default="active",
    )
    origin: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    destination: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    waypoints: Mapped[Any | None] = mapped_column(Geometry("LINESTRING", srid=4326), nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    eta_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recalculation_count: Mapped[int] = mapped_column(Integer, default=0)

    vehicle: Mapped["Vehicle"] = relationship(back_populates="routes")
