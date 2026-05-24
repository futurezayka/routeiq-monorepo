import uuid
from datetime import datetime

from pydantic import BaseModel


class SegmentSpeedRow(BaseModel):
    segment_id: uuid.UUID
    avg_speed: float
    sample_count: int


class HeatmapPoint(BaseModel):
    lat: float
    lng: float
    congestion_level: float


class HeatmapResponse(BaseModel):
    points: list[HeatmapPoint]
    time_from: datetime
    time_to: datetime


class IncidentStatsResponse(BaseModel):
    total: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    avg_resolution_minutes: float | None
    active_count: int
    resolved_count: int
    time_from: datetime
    time_to: datetime


class RouteEfficiencyRow(BaseModel):
    route_id: uuid.UUID
    planned_eta: int | None
    actual_minutes: float
    efficiency: float | None


class FleetEfficiencyResponse(BaseModel):
    routes_total: int
    avg_efficiency: float | None
    avg_recalculations: float
    routes: list[RouteEfficiencyRow]
    time_from: datetime
    time_to: datetime
