import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VehicleCreate(BaseModel):
    license_plate: str
    vehicle_type: str | None = None
    is_simulated: bool = False


class GeoJSONPoint(BaseModel):
    type: str = "Point"
    coordinates: list[float]


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_id: uuid.UUID
    license_plate: str
    vehicle_type: str | None
    status: str
    is_simulated: bool
    last_seen: datetime | None
    current_position: GeoJSONPoint | None = None
