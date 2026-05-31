"""Unit tests for background workers — all deps mocked."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.weather_updater import WeatherUpdaterWorker
from app.workers.traffic_predict_updater import TrafficPredictUpdaterWorker


# ── WeatherUpdaterWorker ──────────────────────────────────────

async def test_weather_updater_runs_and_stops():
    redis = AsyncMock()
    worker = WeatherUpdaterWorker(redis)

    from app.modules.weather.service import WeatherConditions
    cond = WeatherConditions(temperature_c=20.0, condition="clear", wind_kmh=5.0, source="stub")

    with patch.object(worker._weather, "get_current", return_value=cond):
        worker._weights.set_global_weather_factor = AsyncMock()

        async def _stop_after_first():
            await asyncio.sleep(0.01)
            worker.stop()

        await asyncio.gather(worker.run(), _stop_after_first())

    worker._weights.set_global_weather_factor.assert_awaited_once()
    call_kw = worker._weights.set_global_weather_factor.call_args
    assert call_kw[0][0] == 1.0
    assert call_kw[1]["condition"] == "clear"


async def test_weather_updater_handles_error():
    redis = AsyncMock()
    worker = WeatherUpdaterWorker(redis)

    with patch.object(worker._weather, "get_current", side_effect=Exception("boom")):
        async def _stop_soon():
            await asyncio.sleep(0.01)
            worker.stop()

        await asyncio.gather(worker.run(), _stop_soon())


def test_weather_updater_stop():
    worker = WeatherUpdaterWorker(AsyncMock())
    assert not worker._stop.is_set()
    worker.stop()
    assert worker._stop.is_set()


# ── TrafficPredictUpdaterWorker ───────────────────────────────

async def test_predict_updater_sends_requests():
    redis = AsyncMock()
    redis.xadd = AsyncMock()
    session = AsyncMock()
    session_factory = MagicMock()

    repo_mock = AsyncMock()
    repo_mock.list_active_segment_ids = AsyncMock(return_value=["seg-1", "seg-2"])
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    worker = TrafficPredictUpdaterWorker(redis, session_factory)

    with patch("app.workers.traffic_predict_updater.TrafficPredictionRepository", return_value=repo_mock):
        with patch("app.workers.traffic_predict_updater.asyncio.sleep", new_callable=AsyncMock):
            async def _stop_soon():
                await asyncio.sleep(0.01)
                worker.stop()

            await asyncio.gather(worker.run(), _stop_soon())

    assert redis.xadd.await_count == 3


async def test_predict_updater_no_segments():
    redis = AsyncMock()
    redis.xadd = AsyncMock()
    session = AsyncMock()
    session_factory = MagicMock()

    repo_mock = AsyncMock()
    repo_mock.list_active_segment_ids = AsyncMock(return_value=[])
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    worker = TrafficPredictUpdaterWorker(redis, session_factory)

    with patch("app.workers.traffic_predict_updater.TrafficPredictionRepository", return_value=repo_mock):
        with patch("app.workers.traffic_predict_updater.asyncio.sleep", new_callable=AsyncMock):
            async def _stop_soon():
                await asyncio.sleep(0.01)
                worker.stop()

            await asyncio.gather(worker.run(), _stop_soon())

    redis.xadd.assert_not_awaited()


async def test_predict_updater_handles_error():
    redis = AsyncMock()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(side_effect=Exception("db down"))
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    worker = TrafficPredictUpdaterWorker(redis, session_factory)

    with patch("app.workers.traffic_predict_updater.asyncio.sleep", new_callable=AsyncMock):
        async def _stop_soon():
            await asyncio.sleep(0.01)
            worker.stop()

        await asyncio.gather(worker.run(), _stop_soon())


def test_predict_updater_stop():
    worker = TrafficPredictUpdaterWorker(AsyncMock(), MagicMock())
    assert not worker._stop.is_set()
    worker.stop()
    assert worker._stop.is_set()
