import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IncidentCreate(BaseModel):
    type: str
    severity: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    is_simulated: bool = False


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reported_by: uuid.UUID | None
    type: str
    severity: str
    latitude: float
    longitude: float
    is_active: bool
    is_simulated: bool
    reported_at: datetime
    resolved_at: datetime | None
