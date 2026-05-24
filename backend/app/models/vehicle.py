import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.route import Route
    from app.models.user import User


class Vehicle(UUIDMixin, Base):
    __tablename__ = "vehicles"

    driver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    license_plate: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    vehicle_type: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(
        SAEnum("active", "idle", "offline", name="vehicle_status"),
        default="offline",
    )
    current_position: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)

    driver: Mapped["User"] = relationship(back_populates="vehicles")
    routes: Mapped[list["Route"]] = relationship(back_populates="vehicle")
