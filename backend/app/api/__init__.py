from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.incidents import router as incidents_router
from app.api.routes import router as routes_router
from app.api.telemetry import router as telemetry_router
from app.api.vehicles import router as vehicles_router
from app.api.ws import router as ws_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(routes_router)
api_router.include_router(vehicles_router)
api_router.include_router(telemetry_router)
api_router.include_router(incidents_router)
api_router.include_router(analytics_router)
api_router.include_router(admin_router)
api_router.include_router(ws_router)
