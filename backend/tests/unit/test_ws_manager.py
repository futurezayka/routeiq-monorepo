"""Unit tests for WebSocket ConnectionManager — Redis mocked."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws.manager import ConnectionManager


@pytest.fixture
def redis():
    return AsyncMock()


@pytest.fixture
def mgr(redis):
    return ConnectionManager(redis)


def _ws():
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.accept = AsyncMock()
    return ws


# ── connect / accept_and_connect / disconnect ─────────────────

async def test_connect_adds_to_channel(mgr):
    ws = _ws()
    await mgr.connect(ws, "positions")
    assert ws in mgr._channels["positions"]


async def test_connect_default_channel(mgr):
    ws = _ws()
    await mgr.connect(ws)
    assert ws in mgr._channels["positions"]


async def test_accept_and_connect_multi_channel(mgr):
    ws = _ws()
    await mgr.accept_and_connect(ws, ["positions", "incidents"])
    ws.accept.assert_awaited_once()
    assert ws in mgr._channels["positions"]
    assert ws in mgr._channels["incidents"]


def test_disconnect_all_channels(mgr):
    ws = _ws()
    mgr._channels["positions"].add(ws)
    mgr._channels["incidents"].add(ws)
    mgr.disconnect(ws)
    assert ws not in mgr._channels["positions"]
    assert ws not in mgr._channels["incidents"]


def test_disconnect_nonexistent(mgr):
    mgr.disconnect(_ws())


# ── broadcast ─────────────────────────────────────────────────

async def test_broadcast_sends_to_all(mgr):
    ws1, ws2 = _ws(), _ws()
    mgr._channels["positions"] = {ws1, ws2}
    await mgr.broadcast("positions", {"lat": 50.4})
    ws1.send_json.assert_awaited_once_with({"lat": 50.4})
    ws2.send_json.assert_awaited_once_with({"lat": 50.4})


async def test_broadcast_empty_channel(mgr):
    await mgr.broadcast("positions", {"lat": 50.4})


async def test_broadcast_removes_dead_ws(mgr):
    ws_alive = _ws()
    ws_dead = _ws()
    ws_dead.send_json = AsyncMock(side_effect=Exception("disconnected"))
    mgr._channels["positions"] = {ws_alive, ws_dead}
    await mgr.broadcast("positions", {"lat": 50.4})
    assert ws_dead not in mgr._channels["positions"]
    assert ws_alive in mgr._channels["positions"]


# ── stop ──────────────────────────────────────────────────────

def test_stop_sets_event(mgr):
    assert not mgr._stop.is_set()
    mgr.stop()
    assert mgr._stop.is_set()


# ── run_pubsub_listener ─────────────────────────────────────

async def test_pubsub_processes_pmessage(mgr):
    ws = _ws()
    mgr._channels["incidents"] = {ws}

    pubsub = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    call_count = 0

    async def _get(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "type": "pmessage",
                "channel": "ws:incidents",
                "data": json.dumps({"incident_id": "abc"}),
            }
        mgr.stop()
        return None

    pubsub.get_message = AsyncMock(side_effect=_get)
    mgr._redis.pubsub = MagicMock(return_value=pubsub)
    await mgr.run_pubsub_listener()
    ws.send_json.assert_awaited_once_with({"incident_id": "abc"})


async def test_pubsub_skips_non_pmessage(mgr):
    pubsub = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    call_count = 0

    async def _get(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"type": "subscribe", "channel": "ws:*", "data": 1}
        mgr.stop()
        return None

    pubsub.get_message = AsyncMock(side_effect=_get)
    mgr._redis.pubsub = MagicMock(return_value=pubsub)
    await mgr.run_pubsub_listener()


async def test_pubsub_decodes_bytes_channel(mgr):
    ws = _ws()
    mgr._channels["route-updates"] = {ws}

    pubsub = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    call_count = 0

    async def _get(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "type": "pmessage",
                "channel": b"ws:route-updates",
                "data": json.dumps({"route_id": "xyz"}),
            }
        mgr.stop()
        return None

    pubsub.get_message = AsyncMock(side_effect=_get)
    mgr._redis.pubsub = MagicMock(return_value=pubsub)
    await mgr.run_pubsub_listener()
    ws.send_json.assert_awaited_once_with({"route_id": "xyz"})


async def test_pubsub_skips_invalid_json(mgr):
    pubsub = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    call_count = 0

    async def _get(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"type": "pmessage", "channel": "ws:foo", "data": "not-json{{{"}
        mgr.stop()
        return None

    pubsub.get_message = AsyncMock(side_effect=_get)
    mgr._redis.pubsub = MagicMock(return_value=pubsub)
    await mgr.run_pubsub_listener()


async def test_pubsub_reconnects_on_error(mgr, redis):
    pubsub = AsyncMock()
    pubsub.psubscribe = AsyncMock(side_effect=[Exception("conn lost"), AsyncMock()])
    pubsub.punsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    call_count = 0

    async def _get(**kwargs):
        nonlocal call_count
        call_count += 1
        mgr.stop()
        return None

    pubsub.get_message = AsyncMock(side_effect=_get)
    redis.pubsub = MagicMock(return_value=pubsub)

    with patch("app.ws.manager.asyncio.sleep", new_callable=AsyncMock):
        await mgr.run_pubsub_listener()
