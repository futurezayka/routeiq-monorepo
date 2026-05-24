import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from app.events.consumer import BaseStreamConsumer
from app.modules.route_planning.graph_weights import GraphWeightManager
from app.modules.traffic_analysis.prediction_repository import (
    TrafficPredictionRepository,
)

logger = logging.getLogger(__name__)

PREDICT_RESPONSE_STREAM = "stream:ml:predict-response"


class TrafficPredictionConsumer(BaseStreamConsumer):
    """Consumes ML traffic predictions, persists them and updates graph weights."""

    def __init__(self, redis, session_factory) -> None:
        super().__init__(
            redis=redis,
            session_factory=session_factory,
            stream=PREDICT_RESPONSE_STREAM,
            group="traffic-prediction-group",
            consumer_name="traffic-prediction-1",
        )
        self._weights = GraphWeightManager(redis)

    async def process_message(self, msg_id: str, data: dict) -> None:
        try:
            predictions = json.loads(data.get("predictions", "[]"))
            horizon = int(data.get("horizon_minutes", "60"))
            model_version = data.get("model_version", "unknown")
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.exception("Bad predict-response payload %s", msg_id)
            return

        now = datetime.now(UTC)
        target = now + timedelta(minutes=horizon)

        async with self._session_factory() as session, session.begin():
            repo = TrafficPredictionRepository(session)
            for p in predictions:
                try:
                    segment_id = uuid.UUID(p["segment_id"])
                except (KeyError, ValueError):
                    continue
                await repo.insert_prediction(
                    segment_id=segment_id,
                    predicted_at=now,
                    prediction_for=target,
                    congestion_level=float(p.get("congestion", 0)),
                    avg_speed_kmh=float(p.get("avg_speed_kmh", 0)),
                    confidence=float(p.get("confidence", 0)),
                    model_version=model_version,
                )

        if horizon == 60:
            for p in predictions:
                sid = p.get("segment_id")
                if not sid:
                    continue
                congestion = float(p.get("congestion", 0))
                factor = 1.0 + congestion * 2.0
                await self._weights.update_congestion_factor(sid, factor)
