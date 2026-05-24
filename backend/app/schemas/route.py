import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RouteCreate(BaseModel):
    vehicle_id: uuid.UUID
    origin_lat: float = Field(ge=-90, le=90)
    origin_lng: float = Field(ge=-180, le=180)
    destination_lat: float = Field(ge=-90, le=90)
    destination_lng: float = Field(ge=-180, le=180)


class RouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    status: str
    origin_lat: float
    origin_lng: float
    destination_lat: float
    destination_lng: float
    waypoints: list[list[float]] | None
    distance_km: float | None
    eta_minutes: int | None
    recalculation_count: int
    created_at: datetime
