from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import get_auth_service, get_current_user
from app.modules.auth.service import AuthService
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

AuthSvc = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, service: AuthSvc) -> UserResponse:
    """Register a new user."""
    return await service.register(body)


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(body: LoginRequest, service: AuthSvc) -> TokenResponse:
    """Authenticate and receive access + refresh tokens."""
    return await service.login(body)


@router.post("/refresh", status_code=status.HTTP_200_OK)
async def refresh(body: RefreshRequest, service: AuthSvc) -> TokenResponse:
    """Exchange a refresh token for a new access + refresh token pair."""
    return await service.refresh(body)


@router.get("/me", status_code=status.HTTP_200_OK)
async def me(user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """Get current authenticated user."""
    return user
