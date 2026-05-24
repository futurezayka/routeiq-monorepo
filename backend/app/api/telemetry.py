from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import get_agent_service, get_current_user
from app.modules.agent_manager.service import AgentManagerService
from app.schemas.auth import UserResponse
from app.schemas.telemetry import TelemetryCreate

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

AgentSvc = Annotated[AgentManagerService, Depends(get_agent_service)]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def ingest_telemetry(
    body: TelemetryCreate,
    service: AgentSvc,
    user: UserResponse = Depends(get_current_user),
) -> dict:
    """Ingest telemetry. Drivers can only post for their own vehicle."""
    driver_id = user.id if user.role == "driver" else None
    await service.ingest_telemetry(body, driver_id=driver_id)
    return {"status": "accepted"}
