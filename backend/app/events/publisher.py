from redis.asyncio import Redis


class EventBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, stream: str, data: dict) -> str:
        message_id: str = await self._redis.xadd(stream, data)
        return message_id
