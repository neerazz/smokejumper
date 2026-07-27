"""Durable dispatch from admitted Postgres events to Redis Streams.

Postgres owns admission. Redis is a delivery target, not part of that transaction,
so every admitted event remains visibly pending until a successful XADD receipt is
stored back on the row. The fast path dispatches before returning HTTP 202; this
loop closes process-crash and dependency-outage windows.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from smokejumper.queue import producer
from smokejumper.receiver import repository

logger = logging.getLogger(__name__)
_IDLE_SECONDS = 0.25
_RETRY_SECONDS = 1.0


async def dispatch_event(engine: AsyncEngine, redis: Redis, *, event_id: str) -> str | None:
    """Publish one durable event, or return its already-recorded Redis id.

    The event row existed before this function began. Holding its row lock across
    XADD prevents the HTTP fast path and background loop from publishing it at the
    same time. A Redis failure rolls back only the delivery receipt, leaving the
    row pending for retry.
    """
    async with engine.begin() as connection:
        candidate = await repository.event_for_queue(connection, event_id=event_id)
        if candidate is None:
            return None
        event, existing_message_id = candidate
        if existing_message_id is not None:
            return existing_message_id

        message_id = await producer.publish(redis, event)
        await repository.mark_queued(
            connection,
            event_id=event_id,
            message_id=message_id,
            queued_at=datetime.now(tz=UTC),
        )
        return message_id


async def dispatch_pending(engine: AsyncEngine, redis: Redis, *, limit: int = 100) -> int:
    """Offer up to `limit` pending events to Redis; return rows visited."""
    async with engine.connect() as connection:
        event_ids = await repository.pending_queue_event_ids(connection, limit=limit)
    for event_id in event_ids:
        await dispatch_event(engine, redis, event_id=event_id)
    return len(event_ids)


async def pending_count(engine: AsyncEngine) -> int:
    """Read the durable queue-delivery backlog."""
    async with engine.connect() as connection:
        return await repository.pending_queue_count(connection)


async def _run(engine: AsyncEngine, redis: Redis) -> None:
    while True:
        try:
            visited = await dispatch_pending(engine, redis)
            if visited == 0:
                await asyncio.sleep(_IDLE_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("event outbox dispatch failed; retrying")
            await asyncio.sleep(_RETRY_SECONDS)


@dataclass(frozen=True)
class OutboxHandle:
    """Health surface for the process-lifetime dispatcher."""

    task: asyncio.Task[None]

    def status(self) -> str:
        if not self.task.done():
            return "ok"
        if self.task.cancelled():
            return "dead: cancelled"
        error = self.task.exception()
        return "dead: exited" if error is None else f"dead: {type(error).__name__}"


@asynccontextmanager
async def outbox_task(engine: AsyncEngine, redis: Redis) -> AsyncIterator[OutboxHandle]:
    """Run the durable dispatcher for one app lifespan."""
    task = asyncio.create_task(_run(engine, redis), name="event-outbox")
    handle = OutboxHandle(task)
    try:
        yield handle
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
