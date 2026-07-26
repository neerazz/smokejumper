"""Publish normalized events onto the `agentevents` stream (SPEC 5.2).

Redis Streams rather than a list or pub/sub: pub/sub drops messages when no
consumer is attached, and an incident that arrived while the supervisor was
restarting is exactly the one that must survive. A stream is a replayable inbox.

The event is published as its JSON contract under a single `event` field. One
field rather than a flattened map because the consumer reconstructs an
`AgentEvent` and must validate it — flattening would invite reading individual
fields without validation, which is how a payload starts drifting from B2.
"""

from __future__ import annotations

from redis.asyncio import Redis

from smokejumper.contracts.events import AgentEvent

STREAM = "agentevents"

# A stream that grows forever eventually evicts the database from RAM. This bound
# is generous for v1's single-instance scale and is the operator's to raise; the
# audit record, not Redis, is what retains history (SPEC 5.8).
MAX_STREAM_LENGTH = 100_000


async def publish(redis: Redis, event: AgentEvent) -> str:
    """XADD `event` and return the Redis message id.

    The id is returned so the caller can record it in the audit trail: without it
    a run cannot be traced back to the queue entry that started it.
    """
    message_id = await redis.xadd(
        STREAM,
        {"event": event.model_dump_json()},
        maxlen=MAX_STREAM_LENGTH,
        approximate=True,
    )
    return message_id.decode() if isinstance(message_id, bytes) else str(message_id)
