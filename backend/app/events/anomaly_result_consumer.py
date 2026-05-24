import json
import logging

from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.events.consumer import BaseStreamConsumer
from app.models.incident import Incident

logger = logging.getLogger(__name__)

ML_RESPONSE_STREAM = "stream:ml:anomaly-response"

# Throttle: per-segment-bucket cooldown — do not auto-create another incident
# for the same area within this window (Redis SET NX EX). Keeps the map from
# flooding when the ML detector flags a slowly recovering segment repeatedly.
DEDUP_COOLDOWN_S = 600              # 10 minutes per area
DEDUP_BUCKET_DEGREES = 0.01         # ~1km grid for "same area"
SCORE_MIN_FOR_INCIDENT = 0.9        # only very-anomalous scores promote to an incident
MAX_SPEED_FOR_INCIDENT_KMH = 15.0   # absolute floor: ignore "anomalies" at decent speeds


class AnomalyResultConsumer(BaseStreamConsumer):
    """Consumes anomaly detection results from ML service via Redis Streams.

    Creates incidents for detected anomalies and republishes to stream:incidents
    so the rest of the pipeline (reroute, WS) fires normally.
    """

    def __init__(self, redis, session_factory) -> None:
        super().__init__(
            redis=redis,
            session_factory=session_factory,
            stream=ML_RESPONSE_STREAM,
            group="anomaly-result-group",
            consumer_name="anomaly-result-1",
        )

    async def process_message(self, msg_id: str, data: dict) -> None:
        try:
            anomalies = json.loads(data.get("anomalies", "[]"))
        except (json.JSONDecodeError, TypeError):
            logger.exception("Bad anomaly-response payload %s", msg_id)
            return

        for entry in anomalies:
            if not entry.get("is_anomaly"):
                continue

            sid = entry["segment_id"]
            score = float(entry["score"])
            lat = entry.get("lat")
            lng = entry.get("lng")
            if lat is None or lng is None:
                continue

            # Only very-anomalous results promote to an incident
            if score < SCORE_MIN_FOR_INCIDENT:
                continue

            # Absolute floor: ML may flag fast vehicles as "outliers" relative
            # to a slow batch, but those aren't traffic incidents worth alerting.
            avg_speed = entry.get("avg_speed")
            if avg_speed is None or float(avg_speed) > MAX_SPEED_FOR_INCIDENT_KMH:
                continue

            # Per-area cooldown via Redis SET NX EX (atomic test-and-set)
            bucket_lat = round(float(lat) / DEDUP_BUCKET_DEGREES) * DEDUP_BUCKET_DEGREES
            bucket_lng = round(float(lng) / DEDUP_BUCKET_DEGREES) * DEDUP_BUCKET_DEGREES
            dedup_key = f"anomaly:cooldown:{bucket_lat:.4f}:{bucket_lng:.4f}"
            acquired = await self._redis.set(dedup_key, "1", nx=True, ex=DEDUP_COOLDOWN_S)
            if not acquired:
                continue   # area is in cooldown — skip

            severity = "medium" if score < 0.95 else "high"

            async with self._session_factory() as session, session.begin():
                incident = Incident(
                    type="congestion",
                    severity=severity,
                    location=from_shape(Point(lng, lat), srid=4326),
                    is_simulated=False,
                )
                session.add(incident)
                await session.flush()
                incident_id = str(incident.id)

            await self._redis.xadd("stream:incidents", {
                "incident_id": incident_id,
                "type": "congestion",
                "severity": severity,
                "lat": str(lat),
                "lng": str(lng),
            })

            logger.info(
                "Auto-incident %s created for anomaly on %s (score=%.2f)",
                incident_id, sid, score,
            )
