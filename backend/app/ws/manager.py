import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._stop = asyncio.Event()

    async def connect(self, websocket: WebSocket, channel: str = "positions") -> None:
        self._channels[channel].add(websocket)

    async def accept_and_connect(self, websocket: WebSocket, channels: list[str]) -> None:
        await websocket.accept()
        for ch in channels:
            self._channels[ch].add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        for channel_set in self._channels.values():
            channel_set.discard(websocket)

    async def broadcast(self, channel: str, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._channels.get(channel, set()):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def run_pubsub_listener(self) -> None:
        while not self._stop.is_set():
            try:
                pubsub = self._redis.pubsub()
                await pubsub.psubscribe("ws:*")
                logger.info("Pub/Sub listener subscribed to ws:*")
                while not self._stop.is_set():
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0,
                    )
                    if msg is None:
                        continue
                    if msg["type"] != "pmessage":
                        continue
                    channel = msg["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    short = channel.split(":", 1)[-1]
                    try:
                        data = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    await self.broadcast(short, data)
            except Exception:
                logger.exception("Pub/Sub listener error, reconnecting in 2s")
                await asyncio.sleep(2)
            finally:
                try:
                    await pubsub.punsubscribe("ws:*")
                    await pubsub.aclose()
                except Exception:
                    pass

    def stop(self) -> None:
        self._stop.set()
