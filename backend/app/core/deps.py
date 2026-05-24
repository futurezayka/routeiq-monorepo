from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.redis import redis_pool

security_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session, session.begin():
        yield session


async def get_redis() -> Redis:
    return redis_pool


async def get_auth_repo(
    db: AsyncSession = Depends(get_db),
) -> "AuthRepository":
    from app.modules.auth.repository import AuthRepository
    return AuthRepository(db)


async def get_auth_service(
    repo: "AuthRepository" = Depends(get_auth_repo),
) -> "AuthService":
    from app.modules.auth.service import AuthService
    return AuthService(repo)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    service: "AuthService" = Depends(get_auth_service),
) -> "UserResponse":
    from app.core.exceptions import AuthError
    if credentials is None:
        raise AuthError("Not authenticated")
    return await service.get_current_user(credentials.credentials)


def require_role(*roles: str):
    """Dependency factory that allows only users whose role is in `roles`."""
    async def checker(
        user: "UserResponse" = Depends(get_current_user),
    ) -> "UserResponse":
        from app.core.exceptions import ForbiddenError
        if user.role not in roles:
            raise ForbiddenError(
                f"Requires role: {', '.join(roles)}"
            )
        return user
    return checker


async def get_event_bus(
    redis: Redis = Depends(get_redis),
) -> "EventBus":
    from app.events.publisher import EventBus
    return EventBus(redis)


async def get_vehicle_repo(
    db: AsyncSession = Depends(get_db),
) -> "VehicleRepository":
    from app.modules.agent_manager.repository import VehicleRepository
    return VehicleRepository(db)


async def get_agent_service(
    repo: "VehicleRepository" = Depends(get_vehicle_repo),
    redis: Redis = Depends(get_redis),
    event_bus: "EventBus" = Depends(get_event_bus),
) -> "AgentManagerService":
    from app.modules.agent_manager.service import AgentManagerService
    return AgentManagerService(repo, redis, event_bus)


async def get_route_repo(
    db: AsyncSession = Depends(get_db),
) -> "RouteRepository":
    from app.modules.route_planning.repository import RouteRepository
    return RouteRepository(db)


async def get_route_planning_service(
    repo: "RouteRepository" = Depends(get_route_repo),
    event_bus: "EventBus" = Depends(get_event_bus),
    redis: Redis = Depends(get_redis),
) -> "RoutePlanningService":
    from app.modules.route_planning.graph_weights import GraphWeightManager
    from app.modules.route_planning.osrm_client import OSRMClient
    from app.modules.route_planning.service import RoutePlanningService
    return RoutePlanningService(
        repo, OSRMClient(), GraphWeightManager(redis), event_bus, redis,
    )


async def get_analytics_repo(
    db: AsyncSession = Depends(get_db),
) -> "AnalyticsRepository":
    from app.modules.analytics.repository import AnalyticsRepository
    return AnalyticsRepository(db)


async def get_analytics_service(
    repo: "AnalyticsRepository" = Depends(get_analytics_repo),
) -> "AnalyticsService":
    from app.modules.analytics.service import AnalyticsService
    return AnalyticsService(repo)


async def get_admin_repo(
    db: AsyncSession = Depends(get_db),
) -> "AdminRepository":
    from app.modules.admin.repository import AdminRepository
    return AdminRepository(db)


async def get_admin_service(
    repo: "AdminRepository" = Depends(get_admin_repo),
    redis: Redis = Depends(get_redis),
) -> "AdminService":
    from app.modules.admin.service import AdminService
    return AdminService(repo, redis)


async def get_incident_repo(
    db: AsyncSession = Depends(get_db),
) -> "IncidentRepository":
    from app.modules.traffic_analysis.repository import IncidentRepository
    return IncidentRepository(db)


async def get_incident_service(
    repo: "IncidentRepository" = Depends(get_incident_repo),
    event_bus: "EventBus" = Depends(get_event_bus),
) -> "IncidentService":
    from app.modules.traffic_analysis.service import IncidentService
    return IncidentService(repo, event_bus)
