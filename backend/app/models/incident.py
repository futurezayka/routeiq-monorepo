import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class Incident(UUIDMixin, Base):
    __tablename__ = "incidents"

    reported_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    type: Mapped[str] = mapped_column(
        SAEnum("accident", "congestion", "roadwork", "weather", "other", name="incident_type"),
        nullable=False,
    )
    location: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    severity: Mapped[str] = mapped_column(
        SAEnum("low", "medium", "high", name="severity_level"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reporter: Mapped["User"] = relationship(back_populates="reported_incidents")
