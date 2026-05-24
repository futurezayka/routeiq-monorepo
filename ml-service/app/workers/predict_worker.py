import asyncio
import json
import logging

import numpy as np
from redis.asyncio import Redis

from app.models.lstm import TrafficPredictor

logger = logging.getLogger(__name__)

REQUEST_STREAM = "stream:ml:predict-request"
RESPONSE_STREAM = "stream:ml:predict-response"
GROUP = "ml-predict-group"
CONSUMER = "ml-predict-worker-1"


class MLPredictWorker:
    """Consumes prediction requests from backend, runs LSTM, publishes results."""

    def __init__(self, redis: Redis, predictor: TrafficPredictor) -> None:
        self._redis = redis
        self._predictor = predictor
        self._stop = asyncio.Event()

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                REQUEST_STREAM, GROUP, id="0", mkstream=True,
            )
        except Exception:
            pass

    async def _process(self, msg_id: str, data: dict) -> None:
        try:
            request_id = data.get("request_id", "")
            segment_ids = json.loads(data.get("segment_ids", "[]"))
            horizon = int(data.get("horizon_minutes", "60"))
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.exception("Bad predict-request payload %s", msg_id)
            return

        if not segment_ids:
            return

        features = np.zeros(len(segment_ids), dtype=np.float32)
        raw = self._predictor.predict(features)

        predictions = [
            {
                "segment_id": sid,
                "congestion": float(raw[i][0]),
                "avg_speed_kmh": float(raw[i][1]),
                "confidence": float(raw[i][2]),
            }
            for i, sid in enumerate(segment_ids)
        ]

        await self._redis.xadd(RESPONSE_STREAM, {
            "request_id": request_id,
            "horizon_minutes": str(horizon),
            "predictions": json.dumps(predictions),
            "model_version": self._predictor.version,
        })

    async def run(self) -> None:
        await self._ensure_group()
        logger.info("MLPredictWorker started on %s", REQUEST_STREAM)

        while not self._stop.is_set():
            try:
                messages = await self._redis.xreadgroup(
                    groupname=GROUP,
                    consumername=CONSUMER,
                    streams={REQUEST_STREAM: ">"},
                    count=10,
                    block=1000,
                )
            except Exception:
                if self._stop.is_set():
                    break
                logger.exception("Error reading %s", REQUEST_STREAM)
                await asyncio.sleep(1)
                continue

            if not messages:
                continue

            for _stream_name, entries in messages:
                for msg_id, data in entries:
                    try:
                        await self._process(msg_id, data)
                        await self._redis.xack(REQUEST_STREAM, GROUP, msg_id)
                    except Exception:
                        logger.exception("Error processing %s", msg_id)

    def stop(self) -> None:
        self._stop.set()
