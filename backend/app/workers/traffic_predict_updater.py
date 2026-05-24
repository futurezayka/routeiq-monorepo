import asyncio
import json
import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.traffic_analysis.prediction_repository import (
    TrafficPredictionRepository,
)

logger = logging.getLogger(__name__)

PREDICT_REQUEST_STREAM = "stream:ml:predict-request"
UPDATE_INTERVAL_S = 300
HORIZONS_MINUTES = [60, 180, 360]


class TrafficPredictUpdaterWorker:
    """Periodically asks ml-service for predictions on all road segments.

    Sends one request per horizon (1h, 3h, 6h) per cycle.
    Responses arrive on stream:ml:predict-response, handled by TrafficPredictionConsumer.
    """

    def __init__(self, redis: Redis, session_factory: async_sessionmaker) -> None:
        self._redis = redis
        self._session_factory = session_factory
        self._stop = asyncio.Event()

    async def run(self) -> None:
        await asyncio.sleep(10)
        while not self._stop.is_set():
            try:
                async with self._session_factory() as session:
                    repo = TrafficPredictionRepository(session)
                    segment_ids = await repo.list_active_segment_ids()

                if segment_ids:
                    for horizon in HORIZONS_MINUTES:
                        await self._redis.xadd(PREDICT_REQUEST_STREAM, {
                            "request_id": str(uuid.uuid4()),
                            "segment_ids": json.dumps([str(s) for s in segment_ids]),
                            "horizon_minutes": str(horizon),
                        })
                    logger.info(
                        "Queued predictions for %d segments × %d horizons",
                        len(segment_ids), len(HORIZONS_MINUTES),
                    )
            except Exception:
                logger.exception("Predict update cycle failed")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=UPDATE_INTERVAL_S)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
