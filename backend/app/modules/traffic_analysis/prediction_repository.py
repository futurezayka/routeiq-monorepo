import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.road_segment import RoadSegment
from app.models.traffic_prediction import TrafficPrediction


class TrafficPredictionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_segment_ids(self, limit: int = 200) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(RoadSegment.id).limit(limit)
        )
        return list(result.scalars().all())

    async def insert_prediction(
        self,
        segment_id: uuid.UUID,
        predicted_at: datetime,
        prediction_for: datetime,
        congestion_level: float,
        avg_speed_kmh: float,
        confidence: float,
        model_version: str,
    ) -> None:
        record = TrafficPrediction(
            segment_id=segment_id,
            predicted_at=predicted_at,
            prediction_for=prediction_for,
            congestion_level=congestion_level,
            avg_speed_kmh=avg_speed_kmh,
            confidence=confidence,
            model_version=model_version,
        )
        self._session.add(record)
        await self._session.flush()
