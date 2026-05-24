from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import get_analytics_service, require_role
from app.modules.analytics.service import AnalyticsService
from app.schemas.analytics import (
    FleetEfficiencyResponse,
    HeatmapResponse,
    IncidentStatsResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

AnalyticsSvc = Annotated[AnalyticsService, Depends(get_analytics_service)]


@router.get("/heatmap", status_code=status.HTTP_200_OK)
async def get_heatmap(
    service: AnalyticsSvc,
    time_from: datetime = Query(..., alias="from"),
    time_to: datetime = Query(..., alias="to"),
    _user=Depends(require_role("admin", "dispatcher")),
) -> HeatmapResponse:
    """Traffic congestion heatmap (admin/dispatcher only)."""
    return await service.get_traffic_heatmap(time_from, time_to)


@router.get("/incidents", status_code=status.HTTP_200_OK)
async def get_incident_stats(
    service: AnalyticsSvc,
    time_from: datetime = Query(..., alias="from"),
    time_to: datetime = Query(..., alias="to"),
    _user=Depends(require_role("admin", "dispatcher")),
) -> IncidentStatsResponse:
    """Incident statistics (admin/dispatcher only)."""
    return await service.get_incident_stats(time_from, time_to)


@router.get("/efficiency", status_code=status.HTTP_200_OK)
async def get_fleet_efficiency(
    service: AnalyticsSvc,
    time_from: datetime = Query(..., alias="from"),
    time_to: datetime = Query(..., alias="to"),
    _user=Depends(require_role("admin", "dispatcher")),
) -> FleetEfficiencyResponse:
    """Fleet route efficiency metrics (admin/dispatcher only)."""
    return await service.get_fleet_efficiency(time_from, time_to)
