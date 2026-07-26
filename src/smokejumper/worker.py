"""The consumer loop: queue -> triage -> conclusion -> ticket -> audit (SPEC 5.2).

This is the piece that makes an accepted alert lead somewhere. Without it the
Receiver is a very well-tested inbox.

Three properties matter more than the loop itself:

**At-least-once, made idempotent by the ticket index.** A consumer group redelivers
anything not acknowledged, so a crash between `apply()` and `XACK` replays the
message. That is safe because the second pass updates the existing ticket instead
of filing a new one (`actions/service.apply`), which is the same code path a
genuine duplicate alert takes.

**Acknowledge only after the transaction commits.** Acking first would drop an
incident on any failure after it, and a dropped incident is the one failure mode
this system exists to prevent.

**A failing message must not wedge the queue.** One bad payload retried forever
starves every incident behind it, so failures are recorded, acked, and left in the
pending log rather than blocking the stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncEngine

from smokejumper.actions import service
from smokejumper.contracts.events import AgentEvent
from smokejumper.intelligence.triage import triage
from smokejumper.queue.producer import STREAM
from smokejumper.recorder.writer import Recorder

logger = logging.getLogger(__name__)

GROUP = "intelligence"
# Long enough that an idle worker is not spinning, short enough that shutdown is
# responsive: the loop cannot notice cancellation while blocked in XREADGROUP.
BLOCK_MS = 2_000


async def ensure_group(redis: Redis) -> None:
    """Create the consumer group, tolerating the case where it already exists.

    `mkstream=True` so the worker can start before the first alert ever arrives,
    which is the normal order of events on a cold deployment.
    """
    try:
        await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        logger.info("created consumer group %s on %s", GROUP, STREAM)
    except ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise


async def handle(
    engine: AsyncEngine,
    recorder: Recorder,
    event: AgentEvent,
) -> str:
    """Run one event all the way through. Returns the run status."""
    run_id = uuid4()
    started = datetime.now(tz=UTC)
    start_offset = recorder.start_offset()

    async with engine.begin() as connection:
        await service.open_run(
            connection,
            run_id=run_id,
            event_id=event.id,
            fingerprint=event.fingerprint,
            audit_log_file=recorder.path.name,
            audit_start_offset=start_offset,
            started_at=started,
        )

    recorder.record(
        run_id=run_id,
        actor="worker",
        kind="event",
        payload={
            "event_id": str(event.id),
            "fingerprint": event.fingerprint,
            "source": event.source.value,
            "severity": event.severity.value,
        },
    )

    conclusion = triage(event)
    recorder.record(
        run_id=run_id,
        actor="triage",
        kind="transition",
        payload={
            "status": conclusion.status.value,
            "confidence": conclusion.confidence,
            "findings": len(conclusion.findings),
        },
    )

    async with engine.begin() as connection:
        outcome = await service.apply(connection, conclusion)

    _, end_offset = recorder.record(
        run_id=run_id,
        actor="actions",
        kind="action",
        payload={
            "ticket": outcome.external_id,
            "created": outcome.created,
            "update_count": outcome.update_count,
        },
    )

    async with engine.begin() as connection:
        await service.close_run(
            connection,
            run_id=run_id,
            status="concluded",
            conclusion=conclusion,
            audit_end_offset=end_offset,
        )

    logger.info(
        "run %s concluded %s -> ticket %s (%s)",
        run_id,
        conclusion.status.value,
        outcome.external_id,
        "opened" if outcome.created else "updated",
    )
    return conclusion.status.value


async def _process(
    engine: AsyncEngine,
    redis: Redis,
    recorder: Recorder,
    message_id: str,
    fields: dict[bytes | str, bytes | str],
) -> None:
    raw = fields.get(b"event") or fields.get("event")
    if raw is None:
        logger.error("message %s has no event field; acking to unblock", message_id)
        await redis.xack(STREAM, GROUP, message_id)
        return
    try:
        payload = json.loads(raw)
        event = AgentEvent.model_validate(payload)
    except Exception:
        # A payload we cannot parse will never parse. Retrying it forever would
        # starve every incident behind it.
        logger.exception("message %s is unprocessable; acking to unblock", message_id)
        await redis.xack(STREAM, GROUP, message_id)
        return

    try:
        await handle(engine, recorder, event)
    except Exception:
        # Do NOT ack: leave it pending so a retry or an operator can pick it up.
        logger.exception("run failed for message %s; left pending", message_id)
        return

    await redis.xack(STREAM, GROUP, message_id)


async def run_worker(
    engine: AsyncEngine,
    redis: Redis,
    recorder: Recorder,
    *,
    consumer_name: str = "worker-1",
    stop: asyncio.Event | None = None,
) -> None:
    """Consume `agentevents` until cancelled."""
    await ensure_group(redis)
    logger.info("worker %s consuming %s", consumer_name, STREAM)

    while stop is None or not stop.is_set():
        try:
            batch = await redis.xreadgroup(
                GROUP, consumer_name, {STREAM: ">"}, count=10, block=BLOCK_MS
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("xreadgroup failed; retrying")
            await asyncio.sleep(1)
            continue

        # redis-py types xreadgroup loosely; the shape is [(stream, [(id, {..})])].
        for _stream, messages in cast("list[Any]", batch or []):
            for message_id, fields in messages:
                mid = message_id.decode() if isinstance(message_id, bytes) else message_id
                await _process(engine, redis, recorder, mid, fields)


async def queue_depth(redis: Redis) -> dict[str, int]:
    """Unprocessed work on the stream, as two separate numbers.

    Deliberately **not** `XLEN`. XLEN counts every message still retained, which
    on a healthy system grows with every alert ever received and only falls at
    the `maxlen` trim — so alerting on it fires when nothing is wrong, and a
    metric that cries wolf is worse than no metric.

    - `lag`: delivered to nobody yet. This is the real backlog.
    - `pending`: delivered but unacknowledged — in flight, or stuck from a worker
      that died mid-run. Persistently non-zero with `lag` at zero means messages
      are being picked up and dropped, which is a different fault than falling
      behind and wants a different response.
    """
    try:
        groups = cast("list[Mapping[Any, Any]]", await redis.xinfo_groups(STREAM))
    except ResponseError:
        # The stream does not exist until the first alert or `ensure_group`.
        return {"lag": 0, "pending": 0}

    def field(group: Mapping[Any, Any], key: str) -> Any:
        """Read `key` whether redis-py decoded the reply or left it as bytes."""
        return group.get(key, group.get(key.encode()))

    for group in groups:
        name = field(group, "name")
        if isinstance(name, bytes):
            name = name.decode()
        if name == GROUP:
            return {
                "lag": int(field(group, "lag") or 0),
                "pending": int(field(group, "pending") or 0),
            }
    return {"lag": 0, "pending": 0}


class WorkerHandle:
    """Liveness view of the background worker, for the health endpoint.

    Exists because a worker that dies silently is the worst failure this system
    has: the API keeps returning 202, the queue keeps growing, and nothing
    investigates. An orchestrator can only act on that if the health endpoint
    knows about it, so the task is exposed rather than fired and forgotten.
    """

    def __init__(self, task: asyncio.Task[None]) -> None:
        self._task = task

    def status(self) -> str:
        """`ok`, or `dead: <reason>` once the loop has stopped."""
        if not self._task.done():
            return "ok"
        if self._task.cancelled():
            return "dead: cancelled"
        error = self._task.exception()
        return f"dead: {type(error).__name__}" if error else "dead: exited"


@contextlib.asynccontextmanager
async def worker_task(engine: AsyncEngine, redis: Redis, recorder: Recorder):
    """Run the worker beside the API for the lifetime of the app.

    In-process because v1 is explicitly single-instance (SPEC 1). A separate
    deployment unit would need its own scaling and health story for no benefit at
    this scale, and `docker compose up` giving a *complete* system is the point.
    """
    task = asyncio.create_task(run_worker(engine, redis, recorder))
    try:
        yield WorkerHandle(task)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
