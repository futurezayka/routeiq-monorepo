from redis.asyncio import Redis

from app.core.config import settings

redis_pool = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
)
