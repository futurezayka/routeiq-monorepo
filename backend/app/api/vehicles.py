import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import get_agent_service, get_current_user, require_role
from app.modules.agent_manager.service import AgentManagerService
from app.schemas.auth import UserResponse
from app.schemas.vehicle import VehicleCreate, VehicleResponse

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

AgentSvc = Annotated[AgentManagerService, Depends(get_agent_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_vehicle(
    body: VehicleCreate,
    service: AgentSvc,
    user: UserResponse = Depends(require_role("admin", "dispatcher")),
) -> VehicleResponse:
    """Register a new vehicle (admin/dispatcher only)."""
    return await service.register_vehicle(body, str(user.id))


@router.get("", status_code=status.HTTP_200_OK)
async def list_vehicles(
    service: AgentSvc,
    _user: UserResponse = Depends(get_current_user),
) -> list[VehicleResponse]:
    """List all active vehicles."""
    return await service.list_vehicles()


@router.get("/{vehicle_id}", status_code=status.HTTP_200_OK)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    service: AgentSvc,
    _user: UserResponse = Depends(get_current_user),
) -> VehicleResponse:
    """Get a vehicle by ID."""
    return await service.get_vehicle(str(vehicle_id))
