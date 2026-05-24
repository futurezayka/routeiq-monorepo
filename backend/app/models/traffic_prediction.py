import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class TrafficPrediction(UUIDMixin, Base):
    __tablename__ = "traffic_predictions"

    segment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("road_segments.id"))
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prediction_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    congestion_level: Mapped[float | None] = mapped_column(Float)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(50))
