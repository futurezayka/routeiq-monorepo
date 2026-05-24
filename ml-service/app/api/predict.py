import numpy as np
from fastapi import APIRouter, Request, status

from app.schemas import (
    AnomalyRequest,
    AnomalyResponse,
    PredictRequest,
    PredictResponse,
)

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.post(
    "/predict",
    status_code=status.HTTP_200_OK,
    response_model=PredictResponse,
)
async def predict_congestion(
    body: PredictRequest,
    request: Request,
) -> PredictResponse:
    """Predict congestion for given road segments."""
    predictor = request.app.state.traffic_predictor
    features = np.array(
        [body.features.get(sid, 0.0) for sid in body.segment_ids],
        dtype=np.float32,
    ) if body.features else np.zeros(len(body.segment_ids), dtype=np.float32)

    raw = predictor.predict(features)

    return PredictResponse(
        predictions=[
            {
                "segment_id": sid,
                "congestion": float(raw[i][0]),
                "avg_speed_kmh": float(raw[i][1]),
                "confidence": float(raw[i][2]),
            }
            for i, sid in enumerate(body.segment_ids)
        ],
        model_version=predictor.version,
    )


@router.post(
    "/anomaly",
    status_code=status.HTTP_200_OK,
    response_model=AnomalyResponse,
)
async def detect_anomalies(
    body: AnomalyRequest,
    request: Request,
) -> AnomalyResponse:
    """Detect speed anomalies for road segments."""
    detector = request.app.state.anomaly_detector
    segment_ids = list(body.segment_speeds.keys())
    speeds = np.array(
        [body.segment_speeds[sid] for sid in segment_ids],
        dtype=np.float32,
    )

    scores = detector.detect(speeds)

    return AnomalyResponse(
        anomalies=[
            {
                "segment_id": sid,
                "score": float(scores[i]),
                "is_anomaly": bool(scores[i] > detector.threshold),
            }
            for i, sid in enumerate(segment_ids)
        ],
        model_version=detector.version,
    )
