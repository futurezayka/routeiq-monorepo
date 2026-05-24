import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.api import api_router
from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.core.exceptions import AppError, app_error_handler
from app.core.redis import redis_pool
from app.core.security import hash_password
from app.events.anomaly_consumer import AnomalyConsumer
from app.events.anomaly_result_consumer import AnomalyResultConsumer
from app.events.incident_consumer import IncidentAnalysisConsumer
from app.events.route_update_consumer import RouteUpdateConsumer
from app.events.telemetry_consumer import TelemetryConsumer
from app.events.traffic_prediction_consumer import TrafficPredictionConsumer
from app.models.user import User
from app.workers.traffic_predict_updater import TrafficPredictUpdaterWorker
from app.workers.weather_updater import WeatherUpdaterWorker
from app.ws.manager import ConnectionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    force=True,
)
logging.getLogger("app").setLevel(logging.INFO)
logger = logging.getLogger("routeiq")


SEED_ACCOUNTS = [
    ("admin@routeiq.com", "admin123", "Administrator", "admin"),
    ("dispatcher@routeiq.com", "dispatcher123", "Dispatcher", "dispatcher"),
]


async def _ensure_service_accounts() -> None:
    async with async_session_factory() as session, session.begin():
        sim_result = await session.execute(
            select(User).where(User.email == settings.SIM_EMAIL)
        )
        if sim_result.scalar_one_or_none() is None:
            session.add(User(
                email=settings.SIM_EMAIL,
                password_hash=hash_password(settings.SIM_PASSWORD),
                full_name="Simulator",
                role="dispatcher",
            ))
            logger.info("Created service account: %s", settings.SIM_EMAIL)

        for email, password, full_name, role in SEED_ACCOUNTS:
            existing = await session.execute(
                select(User).where(User.email == email)
            )
            if existing.scalar_one_or_none() is None:
                session.add(User(
                    email=email,
                    password_hash=hash_password(password),
                    full_name=full_name,
                    role=role,
                ))
                logger.info("Created seed account: %s (%s)", email, role)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await redis_pool.ping()
    await _ensure_service_accounts()

    consumers = [
        TelemetryConsumer(redis_pool, async_session_factory),
        IncidentAnalysisConsumer(redis_pool, async_session_factory),
        RouteUpdateConsumer(redis_pool, async_session_factory),
        AnomalyConsumer(redis_pool, async_session_factory),
        AnomalyResultConsumer(redis_pool, async_session_factory),
        TrafficPredictionConsumer(redis_pool, async_session_factory),
    ]
    tasks = [asyncio.create_task(c.run()) for c in consumers]

    weather_worker = WeatherUpdaterWorker(redis_pool)
    weather_task = asyncio.create_task(weather_worker.run())
    predict_updater = TrafficPredictUpdaterWorker(redis_pool, async_session_factory)
    predict_updater_task = asyncio.create_task(predict_updater.run())

    ws_manager = ConnectionManager(redis_pool)
    app.state.ws_manager = ws_manager
    pubsub_task = asyncio.create_task(ws_manager.run_pubsub_listener())

    yield

    for c in consumers:
        c.stop()
    weather_worker.stop()
    predict_updater.stop()
    ws_manager.stop()
    for t in tasks:
        await t
    await weather_task
    await predict_updater_task
    await pubsub_task
    await redis_pool.aclose()
    await engine.dispose()


app = FastAPI(
    title="RouteIQ",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_exception_handler(AppError, app_error_handler)
app.include_router(api_router)
