import asyncio
import json
import logging

import numpy as np
from redis.asyncio import Redis

from app.models.isolation_forest import AnomalyDetector

logger = logging.getLogger(__name__)

REQUEST_STREAM = "stream:ml:anomaly-request"
RESPONSE_STREAM = "stream:ml:anomaly-response"
GROUP = "ml-anomaly-group"
CONSUMER = "ml-anomaly-worker-1"


class MLAnomalyWorker:
    def __init__(self, redis: Redis, detector: AnomalyDetector) -> None:
        self._redis = redis
        self._detector = detector
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
            segments = json.loads(data.get("segments", "[]"))
        except (json.JSONDecodeError, TypeError):
            logger.exception("Bad anomaly-request payload %s", msg_id)
            return

        if not segments:
            return

        speeds = np.array(
            [float(s.get("avg_speed", 0)) for s in segments],
            dtype=np.float32,
        )
        scores = self._detector.detect(speeds)

        anomalies = [
            {
                "segment_id": segments[i]["segment_id"],
                "score": float(scores[i]),
                "is_anomaly": bool(scores[i] > self._detector.threshold),
                "lat": segments[i].get("lat"),
                "lng": segments[i].get("lng"),
                "avg_speed": float(speeds[i]),
            }
            for i in range(len(segments))
        ]

        await self._redis.xadd(RESPONSE_STREAM, {
            "request_id": request_id,
            "anomalies": json.dumps(anomalies),
            "model_version": self._detector.version,
        })

    async def run(self) -> None:
        await self._ensure_group()
        logger.info("MLAnomalyWorker started on %s", REQUEST_STREAM)

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
