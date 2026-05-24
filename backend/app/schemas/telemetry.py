import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TelemetryCreate(BaseModel):
    vehicle_id: uuid.UUID
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed_kmh: float | None = Field(default=None, ge=0)
    heading: float | None = Field(default=None, ge=0, lt=360)


class TelemetryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    time: datetime
    vehicle_id: uuid.UUID
    latitude: float
    longitude: float
    speed_kmh: float | None
    heading: float | None
