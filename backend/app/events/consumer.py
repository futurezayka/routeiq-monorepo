import abc
import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class BaseStreamConsumer(abc.ABC):
    MAX_RETRIES = 3
    CLAIM_IDLE_MS = 60_000

    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker,
        stream: str,
        group: str,
        consumer_name: str,
    ) -> None:
        self._redis = redis
        self._session_factory = session_factory
        self._stream = stream
        self._group = group
        self._consumer_name = consumer_name
        self._stop = asyncio.Event()

    async def _ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                self._stream, self._group, id="0", mkstream=True,
            )
        except Exception:
            pass

    @abc.abstractmethod
    async def process_message(self, msg_id: str, data: dict) -> None: ...

    async def _get_delivery_count(self, msg_id: str) -> int:
        try:
            info = await self._redis.xpending_range(
                self._stream, self._group,
                min=msg_id, max=msg_id, count=1,
            )
            if info:
                return info[0].get("times_delivered", 1)
        except Exception:
            pass
        return 1

    async def _process_pending(self) -> None:
        try:
            result = await self._redis.xautoclaim(
                self._stream, self._group, self._consumer_name,
                min_idle_time=self.CLAIM_IDLE_MS, start_id="0-0", count=50,
            )
            _next_id, entries, _deleted = result
        except Exception:
            return

        for msg_id, data in entries:
            if data is None:
                await self._redis.xack(self._stream, self._group, msg_id)
                continue

            delivery_count = await self._get_delivery_count(msg_id)
            if delivery_count > self.MAX_RETRIES:
                logger.warning(
                    "Dead-letter: %s on %s after %d attempts",
                    msg_id, self._stream, delivery_count,
                )
                await self._redis.xack(self._stream, self._group, msg_id)
                continue

            try:
                await self.process_message(msg_id, data)
                await self._redis.xack(self._stream, self._group, msg_id)
            except Exception:
                logger.exception(
                    "Retry failed for %s on %s (attempt %d/%d)",
                    msg_id, self._stream, delivery_count, self.MAX_RETRIES,
                )

    async def run(self) -> None:
        await self._ensure_group()
        while not self._stop.is_set():
            await self._process_pending()

            try:
                messages = await self._redis.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer_name,
                    streams={self._stream: ">"},
                    count=50,
                    block=500,
                )
            except Exception:
                if self._stop.is_set():
                    break
                logger.exception("Error reading from %s", self._stream)
                await self._ensure_group()
                await asyncio.sleep(1)
                continue

            if not messages:
                continue

            for _stream_name, entries in messages:
                for msg_id, data in entries:
                    try:
                        await self.process_message(msg_id, data)
                        await self._redis.xack(
                            self._stream, self._group, msg_id,
                        )
                    except Exception:
                        logger.exception("Error processing %s", msg_id)

    def stop(self) -> None:
        self._stop.set()
