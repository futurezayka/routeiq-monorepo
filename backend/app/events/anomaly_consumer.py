import json
import logging
import time
import uuid
from collections import defaultdict

from app.events.consumer import BaseStreamConsumer

logger = logging.getLogger(__name__)

ML_REQUEST_STREAM = "stream:ml:anomaly-request"
BATCH_SIZE = 50
FLUSH_INTERVAL_S = 30


class AnomalyConsumer(BaseStreamConsumer):
    """Reads telemetry, batches segment speeds, sends to ML via Redis Streams.

    Replaces the old REST POST to ml-service /api/v1/ml/anomaly.
    Responses arrive asynchronously and are handled by AnomalyResultConsumer.
    """

    def __init__(self, redis, session_factory) -> None:
        super().__init__(
            redis=redis,
            session_factory=session_factory,
            stream="stream:telemetry",
            group="anomaly-detection-group",
            consumer_name="anomaly-detector-1",
        )
        self._segment_speeds: dict[str, list[float]] = defaultdict(list)
        self._segment_coords: dict[str, tuple[float, float]] = {}
        self._msg_count = 0
        self._last_flush = time.monotonic()

    async def process_message(self, msg_id: str, data: dict) -> None:
        speed = float(data.get("speed", 0))
        lat = float(data.get("lat", 0))
        lng = float(data.get("lng", 0))
        segment_id = data.get("road_segment_id")

        if not segment_id:
            segment_id = f"virtual_{round(lat, 3)}_{round(lng, 3)}"

        self._segment_speeds[segment_id].append(speed)
        self._segment_coords[segment_id] = (lat, lng)
        self._msg_count += 1

        elapsed = time.monotonic() - self._last_flush
        if self._msg_count >= BATCH_SIZE or elapsed >= FLUSH_INTERVAL_S:
            await self._dispatch_to_ml()

    async def _dispatch_to_ml(self) -> None:
        if not self._segment_speeds:
            return

        segments = []
        for sid, speeds in self._segment_speeds.items():
            avg = sum(speeds) / len(speeds)
            lat, lng = self._segment_coords.get(sid, (0.0, 0.0))
            segments.append({
                "segment_id": sid,
                "avg_speed": avg,
                "lat": lat,
                "lng": lng,
            })

        self._segment_speeds.clear()
        self._segment_coords.clear()
        self._msg_count = 0
        self._last_flush = time.monotonic()

        try:
            await self._redis.xadd(ML_REQUEST_STREAM, {
                "request_id": str(uuid.uuid4()),
                "segments": json.dumps(segments),
            })
        except Exception:
            logger.exception("Failed to publish ML anomaly request")
