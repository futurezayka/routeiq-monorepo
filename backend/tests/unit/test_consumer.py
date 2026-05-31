"""Unit tests for BaseStreamConsumer — Redis mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.events.consumer import BaseStreamConsumer


class _StubConsumer(BaseStreamConsumer):
    def __init__(self, redis, stream="s", group="g"):
        super().__init__(
            redis=redis,
            session_factory=MagicMock(),
            stream=stream,
            group=group,
            consumer_name="c",
        )
        self.processed: list[tuple] = []

    async def process_message(self, msg_id, data):
        self.processed.append((msg_id, data))


class _FailConsumer(_StubConsumer):
    async def process_message(self, msg_id, data):
        raise RuntimeError("boom")


@pytest.fixture
def redis():
    r = AsyncMock()
    r.xgroup_create = AsyncMock()
    r.xreadgroup = AsyncMock(return_value=[])
    r.xautoclaim = AsyncMock(return_value=("0-0", [], []))
    r.xack = AsyncMock()
    r.xpending_range = AsyncMock(return_value=[])
    return r


@pytest.fixture
def consumer(redis):
    return _StubConsumer(redis)


# ── _ensure_group ─────────────────────────────────────────────

async def test_ensure_group_creates(consumer, redis):
    await consumer._ensure_group()
    redis.xgroup_create.assert_awaited_once_with("s", "g", id="0", mkstream=True)


async def test_ensure_group_ignores_error(consumer, redis):
    redis.xgroup_create.side_effect = Exception("BUSYGROUP")
    await consumer._ensure_group()


# ── _get_delivery_count ───────────────────────────────────────

async def test_delivery_count_from_redis(consumer, redis):
    redis.xpending_range.return_value = [{"times_delivered": 3}]
    assert await consumer._get_delivery_count("1-0") == 3


async def test_delivery_count_empty(consumer, redis):
    redis.xpending_range.return_value = []
    assert await consumer._get_delivery_count("1-0") == 1


async def test_delivery_count_error_fallback(consumer, redis):
    redis.xpending_range.side_effect = Exception("e")
    assert await consumer._get_delivery_count("1-0") == 1


# ── _process_pending ──────────────────────────────────────────

async def test_pending_processes_messages(consumer, redis):
    redis.xautoclaim.return_value = ("0-0", [("m1", {"k": "v"}), ("m2", {"k2": "v2"})], [])
    redis.xpending_range.return_value = [{"times_delivered": 1}]
    await consumer._process_pending()
    assert len(consumer.processed) == 2
    assert redis.xack.await_count == 2


async def test_pending_dead_letters(consumer, redis):
    redis.xautoclaim.return_value = ("0-0", [("m-dead", {"k": "v"})], [])
    redis.xpending_range.return_value = [{"times_delivered": 5}]
    await consumer._process_pending()
    assert len(consumer.processed) == 0
    redis.xack.assert_awaited_once()


async def test_pending_acks_none_data(consumer, redis):
    redis.xautoclaim.return_value = ("0-0", [("m-x", None)], [])
    await consumer._process_pending()
    redis.xack.assert_awaited_once()
    assert len(consumer.processed) == 0


async def test_pending_xautoclaim_error(consumer, redis):
    redis.xautoclaim.side_effect = Exception("network")
    await consumer._process_pending()


async def test_pending_process_error_logged(redis):
    consumer = _FailConsumer(redis)
    redis.xautoclaim.return_value = ("0-0", [("m-e", {"k": "v"})], [])
    redis.xpending_range.return_value = [{"times_delivered": 1}]
    await consumer._process_pending()


# ── run / stop ────────────────────────────────────────────────

async def test_run_reads_and_processes(consumer, redis):
    call_count = 0

    async def _xrg(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [("s", [("1-0", {"foo": "bar"})])]
        consumer.stop()
        return []

    redis.xreadgroup = AsyncMock(side_effect=_xrg)
    await consumer.run()
    assert ("1-0", {"foo": "bar"}) in consumer.processed


async def test_run_handles_read_error(consumer, redis):
    call_count = 0

    async def _xrg(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Redis gone")
        consumer.stop()
        return []

    redis.xreadgroup = AsyncMock(side_effect=_xrg)
    with patch("app.events.consumer.asyncio.sleep", new_callable=AsyncMock):
        await consumer.run()


async def test_run_handles_process_error(redis):
    consumer = _FailConsumer(redis)
    call_count = 0

    async def _xrg(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [("s", [("1-0", {"foo": "bar"})])]
        consumer.stop()
        return []

    redis.xreadgroup = AsyncMock(side_effect=_xrg)
    await consumer.run()


def test_stop_sets_flag(consumer):
    assert not consumer._stop.is_set()
    consumer.stop()
    assert consumer._stop.is_set()


async def test_run_skips_empty_messages(consumer, redis):
    call_count = 0

    async def _xrg(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []
        consumer.stop()
        return []

    redis.xreadgroup = AsyncMock(side_effect=_xrg)
    await consumer.run()
    assert len(consumer.processed) == 0
