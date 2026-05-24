import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import get_current_user, get_incident_service, require_role
from app.modules.traffic_analysis.service import IncidentService
from app.schemas.auth import UserResponse
from app.schemas.incident import IncidentCreate, IncidentResponse

router = APIRouter(prefix="/incidents", tags=["incidents"])

IncidentSvc = Annotated[IncidentService, Depends(get_incident_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def report_incident(
    body: IncidentCreate,
    service: IncidentSvc,
    user: UserResponse = Depends(get_current_user),
) -> IncidentResponse:
    """Report a new incident (any authenticated role — drivers report from field)."""
    return await service.report_incident(body, user.id)


@router.get("", status_code=status.HTTP_200_OK)
async def list_incidents(
    service: IncidentSvc,
    _user: UserResponse = Depends(get_current_user),
    type: str | None = Query(None),
) -> list[IncidentResponse]:
    """List active incidents, optionally filtered by type."""
    return await service.list_incidents(type)


@router.patch("/{incident_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_incident(
    incident_id: uuid.UUID,
    service: IncidentSvc,
    user: UserResponse = Depends(require_role("admin", "dispatcher")),
) -> IncidentResponse:
    """Resolve (deactivate) an incident (admin/dispatcher only)."""
    return await service.resolve_incident(incident_id)


@router.post("/resolve-stale", status_code=status.HTTP_200_OK)
async def resolve_stale_incidents(
    service: IncidentSvc,
    _user: UserResponse = Depends(require_role("admin", "dispatcher")),
    max_age_hours: int = Query(1, ge=1),
) -> dict[str, int]:
    """Resolve all incidents older than max_age_hours (admin/dispatcher only)."""
    count = await service.resolve_stale(max_age_hours)
    return {"resolved": count}
