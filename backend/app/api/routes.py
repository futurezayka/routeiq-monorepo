import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import get_current_user, get_route_planning_service, require_role
from app.modules.route_planning.service import RoutePlanningService
from app.schemas.auth import UserResponse
from app.schemas.route import RouteCreate, RouteResponse

router = APIRouter(tags=["routes"])

RouteSvc = Annotated[RoutePlanningService, Depends(get_route_planning_service)]


@router.get("/routes", status_code=status.HTTP_200_OK)
async def list_routes(
    service: RouteSvc,
    _user: UserResponse = Depends(get_current_user),
) -> list[RouteResponse]:
    """List all active routes."""
    return await service.list_routes()


@router.post("/routes", status_code=status.HTTP_201_CREATED)
async def plan_route(
    body: RouteCreate,
    service: RouteSvc,
    _user: UserResponse = Depends(require_role("admin", "dispatcher")),
) -> RouteResponse:
    """Assign a new route to a vehicle (admin/dispatcher only)."""
    return await service.plan_route(body)


@router.get("/routes/{route_id}", status_code=status.HTTP_200_OK)
async def get_route(
    route_id: uuid.UUID,
    service: RouteSvc,
    _user: UserResponse = Depends(get_current_user),
) -> RouteResponse:
    """Get a route by ID."""
    return await service.get_route(route_id)


@router.get("/vehicles/{vehicle_id}/route", status_code=status.HTTP_200_OK)
async def get_vehicle_active_route(
    vehicle_id: uuid.UUID,
    service: RouteSvc,
    _user: UserResponse = Depends(get_current_user),
) -> RouteResponse:
    """Get the active route for a vehicle."""
    return await service.get_active_route(vehicle_id)
