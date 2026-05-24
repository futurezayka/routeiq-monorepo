from jose import JWTError

from app.core.exceptions import AuthError, ConflictError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.modules.auth.repository import AuthRepository
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)


class AuthService:
    def __init__(self, repo: AuthRepository) -> None:
        self._repo = repo

    def _create_token_pair(self, user_id: str, role: str) -> TokenResponse:
        access = create_access_token({"sub": user_id, "role": role})
        refresh = create_refresh_token({"sub": user_id})
        return TokenResponse(access_token=access, refresh_token=refresh)

    async def register(self, data: UserCreate) -> UserResponse:
        existing = await self._repo.get_by_email(data.email)
        if existing:
            raise ConflictError("Email already registered")

        user = await self._repo.create_user({
            "email": data.email,
            "password_hash": hash_password(data.password),
            "full_name": data.full_name,
            "role": data.role,
        })
        return UserResponse.model_validate(user)

    async def login(self, data: LoginRequest) -> TokenResponse:
        user = await self._repo.get_by_email(data.email)
        if not user or not verify_password(data.password, user.password_hash):
            raise AuthError("Invalid email or password")

        return self._create_token_pair(str(user.id), user.role)

    async def refresh(self, data: RefreshRequest) -> TokenResponse:
        try:
            payload = decode_refresh_token(data.refresh_token)
        except JWTError:
            raise AuthError("Invalid or expired refresh token")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthError("Invalid refresh token")

        user = await self._repo.get_by_id(user_id)
        if not user:
            raise AuthError("User not found")

        return self._create_token_pair(str(user.id), user.role)

    async def get_current_user(self, token: str) -> UserResponse:
        try:
            payload = decode_access_token(token)
        except JWTError:
            raise AuthError("Invalid token")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthError("Invalid token")

        user = await self._repo.get_by_id(user_id)
        if not user:
            raise AuthError("User not found")

        return UserResponse.model_validate(user)
