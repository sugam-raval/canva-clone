"""Progress fan-out — IMPLEMENTATION_PLAN §0.9.

"Progress is published to Redis pub/sub on channel `progress:{requestId}` and fanned
out over WebSocket."

Redis is the transport so that the worker publishing events and the API process holding
the WebSocket need not be the same process. When Redis is unavailable the bus falls back
to an in-process broadcast, which keeps single-process development working.

Every event is also retained in a short replay buffer, so a client that connects a
moment after the request started still receives `doc.skeleton` rather than waiting
forever for an event it already missed.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

import structlog
from pydantic import BaseModel

from app.config import get_settings

log = structlog.get_logger(__name__)

CHANNEL = "progress:{request_id}"
REPLAY_LIMIT = 200
TERMINAL = {"request.done", "request.failed", "request.clarify"}


class ProgressBus:
    def __init__(self) -> None:
        self._redis: Any | None = None
        self._redis_failed = False
        self._local: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._replay: dict[str, deque] = defaultdict(lambda: deque(maxlen=REPLAY_LIMIT))
        self._lock = asyncio.Lock()

    async def _get_redis(self):
        if self._redis is not None or self._redis_failed:
            return self._redis
        async with self._lock:
            if self._redis is None and not self._redis_failed:
                try:
                    import redis.asyncio as aioredis

                    client = aioredis.from_url(get_settings().redis_url,
                                               decode_responses=True)
                    await client.ping()
                    self._redis = client
                except Exception as exc:  # noqa: BLE001
                    log.warning("progress.redis_unavailable", error=str(exc))
                    self._redis_failed = True
        return self._redis

    async def publish(self, request_id: str, event: BaseModel | dict) -> None:
        payload = (event.model_dump(by_alias=True, exclude_none=True)
                   if isinstance(event, BaseModel) else dict(event))
        text = json.dumps(payload, separators=(",", ":"), default=str)

        self._replay[request_id].append(text)
        for queue in list(self._local.get(request_id, ())):
            queue.put_nowait(text)

        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.publish(CHANNEL.format(request_id=request_id), text)
                # Retain for late subscribers on other processes.
                key = f"progress:replay:{request_id}"
                await redis.rpush(key, text)
                await redis.ltrim(key, -REPLAY_LIMIT, -1)
                await redis.expire(key, 3600)
            except Exception as exc:  # noqa: BLE001
                log.warning("progress.publish_failed", error=str(exc))

    async def subscribe(self, request_id: str) -> AsyncIterator[str]:
        """Yield replayed events first, then live ones, until a terminal event."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._local[request_id].add(queue)
        seen = 0
        try:
            redis = await self._get_redis()
            replay: list[str] = list(self._replay.get(request_id, ()))
            if redis is not None and not replay:
                try:
                    replay = await redis.lrange(f"progress:replay:{request_id}", 0, -1)
                except Exception:  # noqa: BLE001
                    replay = []
            for text in replay:
                seen += 1
                yield text
                if _is_terminal(text):
                    return

            if redis is None:
                while True:
                    text = await queue.get()
                    yield text
                    if _is_terminal(text):
                        return
                return

            pubsub = redis.pubsub()
            await pubsub.subscribe(CHANNEL.format(request_id=request_id))
            try:
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True,
                                                       timeout=30.0)
                    if message is None:
                        # Keep the socket alive through quiet stretches of GPU work.
                        yield json.dumps({"t": "ping"})
                        continue
                    text = message["data"]
                    yield text
                    if _is_terminal(text):
                        return
            finally:
                await pubsub.unsubscribe()
                await pubsub.close()
        finally:
            self._local[request_id].discard(queue)
            if not self._local[request_id]:
                self._local.pop(request_id, None)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None


def _is_terminal(text: str) -> bool:
    try:
        return json.loads(text).get("t") in TERMINAL
    except (ValueError, AttributeError):
        return False


_bus = ProgressBus()


def get_bus() -> ProgressBus:
    return _bus


def emitter(request_id: str):
    """An `emit` callable for the orchestrator, bound to one request."""

    async def emit(event) -> None:
        await _bus.publish(request_id, event)

    return emit
