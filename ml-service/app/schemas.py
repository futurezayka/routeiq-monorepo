from pydantic import BaseModel


class PredictRequest(BaseModel):
    segment_ids: list[str]
    features: dict[str, float] | None = None


class SegmentPrediction(BaseModel):
    segment_id: str
    congestion: float
    avg_speed_kmh: float
    confidence: float


class PredictResponse(BaseModel):
    predictions: list[SegmentPrediction]
    model_version: str


class AnomalyRequest(BaseModel):
    segment_speeds: dict[str, float]


class SegmentAnomaly(BaseModel):
    segment_id: str
    score: float
    is_anomaly: bool


class AnomalyResponse(BaseModel):
    anomalies: list[SegmentAnomaly]
    model_version: str
