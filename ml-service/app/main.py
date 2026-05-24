import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import ConnectionPool, Redis

from app.api.predict import router as predict_router
from app.core.config import settings
from app.models.isolation_forest import AnomalyDetector
from app.models.lstm import TrafficPredictor
from app.models.prophet_fallback import ProphetFallback
from app.workers.anomaly_worker import MLAnomalyWorker
from app.workers.predict_worker import MLPredictWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ml-service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
    redis = Redis(connection_pool=pool)
    await redis.ping()

    detector = AnomalyDetector()
    predictor = TrafficPredictor()
    app.state.traffic_predictor = predictor
    app.state.anomaly_detector = detector
    app.state.prophet_fallback = ProphetFallback()

    anomaly_worker = MLAnomalyWorker(redis, detector)
    predict_worker = MLPredictWorker(redis, predictor)
    workers = [anomaly_worker, predict_worker]
    worker_tasks = [asyncio.create_task(w.run()) for w in workers]

    try:
        yield
    finally:
        for w in workers:
            w.stop()
        for t in worker_tasks:
            await t
        await redis.aclose()
        await pool.aclose()


app = FastAPI(
    title="RouteIQ ML Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(predict_router)
