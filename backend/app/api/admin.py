from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import get_admin_service, require_role
from app.modules.admin.service import AdminService
from app.schemas.auth import UserCreate, UserResponse

router = APIRouter(prefix="/admin", tags=["admin"])

AdminSvc = Annotated[AdminService, Depends(get_admin_service)]


@router.post("/reset-simulation", status_code=status.HTTP_200_OK)
async def reset_simulation(
    service: AdminSvc,
    _user: UserResponse = Depends(require_role("admin", "dispatcher")),
) -> dict[str, int]:
    """Delete all simulated vehicles, incidents, routes, and telemetry."""
    return await service.reset_simulation_data()


@router.get("/random-road-point", status_code=status.HTTP_200_OK)
async def random_road_point(
    service: AdminSvc,
    _user: UserResponse = Depends(require_role("admin", "dispatcher")),
    n: int = Query(1, ge=1, le=20),
    categories: str | None = Query(
        None,
        description=(
            "Comma-separated road_type filter. Defaults to major roads "
            "(motorway, trunk, primary, secondary, tertiary)."
        ),
    ),
) -> list[dict[str, float]]:
    """Random (lat, lng) points that lie ON a road segment.

    The simulator calls this to place incidents on real, drivable roads
    rather than uniformly sampling a bbox (which lands incidents in the
    Dnipro, lakes, and parks).
    """
    cats: tuple[str, ...] | None = None
    if categories:
        cats = tuple(c.strip() for c in categories.split(",") if c.strip())
    return await service.random_road_points(n=n, categories=cats)


@router.get("/users", status_code=status.HTTP_200_OK)
async def list_users(
    service: AdminSvc,
    _user: UserResponse = Depends(require_role("admin")),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    role: str | None = Query(None),
    search: str | None = Query(None),
) -> dict:
    """List users with pagination, filtering, and search (admin only)."""
    offset = (page - 1) * per_page
    return await service.list_users_paginated(
        offset=offset, limit=per_page, role=role, search=search,
    )


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    service: AdminSvc,
    _user: UserResponse = Depends(require_role("admin")),
) -> UserResponse:
    """Create a new user (admin only)."""
    return await service.create_user(body)
