import logging

from redis.asyncio import Redis

from app.core.exceptions import ConflictError
from app.core.security import hash_password
from app.modules.admin.repository import AdminRepository
from app.schemas.auth import UserCreate, UserResponse

logger = logging.getLogger(__name__)

_STREAMS_TO_CLEAN = ("stream:telemetry", "stream:incidents", "stream:incidents:analyzed", "stream:route-updates")
_CONSUMER_GROUPS = {
    "stream:telemetry": ("agent-manager-group", "traffic-analysis-group"),
    "stream:incidents": ("traffic-analysis-group",),
    "stream:incidents:analyzed": ("route-planning-group",),
    "stream:route-updates": ("agent-manager-group",),
}


class AdminService:
    def __init__(self, repo: AdminRepository, redis: Redis) -> None:
        self._repo = repo
        self._redis = redis

    async def list_users(self) -> list[UserResponse]:
        users = await self._repo.list_users()
        return [UserResponse.model_validate(u) for u in users]

    async def list_users_paginated(
        self,
        offset: int = 0,
        limit: int = 20,
        role: str | None = None,
        search: str | None = None,
    ) -> dict:
        users, total = await self._repo.list_users_paginated(
            offset=offset, limit=limit, role=role, search=search,
        )
        return {
            "users": [UserResponse.model_validate(u) for u in users],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    async def create_user(self, data: UserCreate) -> UserResponse:
        if await self._repo.get_user_by_email(data.email):
            raise ConflictError("Email already registered")
        user = await self._repo.create_user({
            "email": data.email,
            "password_hash": hash_password(data.password),
            "full_name": data.full_name,
            "role": data.role,
        })
        return UserResponse.model_validate(user)

    async def reset_simulation_data(self) -> dict[str, int]:
        sim_vehicle_ids = await self._repo.get_simulated_vehicle_ids()

        deleted_routes = await self._repo.delete_routes_for_vehicles(sim_vehicle_ids)
        deleted_telemetry = await self._repo.delete_telemetry_for_vehicles(sim_vehicle_ids)
        deleted_incidents = await self._repo.delete_simulated_incidents()
        deleted_vehicles = await self._repo.delete_simulated_vehicles()

        stream_messages_trimmed = 0
        for stream in _STREAMS_TO_CLEAN:
            try:
                trimmed = await self._redis.xtrim(stream, maxlen=0)
                stream_messages_trimmed += trimmed
            except Exception:
                pass
            for group in _CONSUMER_GROUPS.get(stream, ()):
                try:
                    await self._redis.xgroup_destroy(stream, group)
                except Exception:
                    pass

        logger.info(
            "Simulation reset: %d vehicles, %d routes, %d telemetry, %d stream msgs",
            deleted_vehicles, deleted_routes, deleted_telemetry, stream_messages_trimmed,
        )

        return {
            "deleted_vehicles": deleted_vehicles,
            "deleted_incidents": deleted_incidents,
            "deleted_routes": deleted_routes,
            "deleted_telemetry": deleted_telemetry,
            "stream_messages_trimmed": stream_messages_trimmed,
        }

    async def random_road_points(
        self,
        n: int = 1,
        categories: tuple[str, ...] | None = None,
    ) -> list[dict[str, float]]:
        """Return N random (lat, lng) points on major roads.

        Used by the simulator to inject incidents only on actual drivable
        roads (avoids the Dnipro / parks / private dwellings that random
        bbox sampling produces).
        """
        pts = await self._repo.random_road_points(
            n=n,
            categories=categories or (
                "motorway", "trunk", "primary", "secondary", "tertiary",
            ),
        )
        return [{"lat": lat, "lng": lng} for lat, lng in pts]
