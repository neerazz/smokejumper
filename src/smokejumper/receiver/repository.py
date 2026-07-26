"""Reads and writes for the `events` table (SPEC 5.1, 7).

Raw SQL rather than ORM models: M0 deliberately shipped no ORM layer, and the
two statements here are simpler as SQL than the mapping that would describe them.

The dedupe decision is serialized per fingerprint by a transaction-scoped
advisory lock. Two deliveries of the same alert arrive concurrently in a storm by
definition, so an unsynchronized "look for an open event, otherwise insert" lets
both see nothing and file two tickets — the exact failure the fingerprint exists
to prevent.

An advisory lock rather than a unique index, because the open window is
*time-relative*: `received_at > now() - 15 minutes` cannot appear in an index
predicate, since a partial index requires an immutable expression. A unique index
on `fingerprint` alone would be wrong in the other direction — it would forbid a
genuine new incident with the same fingerprint after the window expired. The lock
is taken on a hash of the fingerprint and released when the transaction ends, so
concurrent deliveries of *different* incidents never block each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from smokejumper.contracts.events import AgentEvent

# SPEC 5.1: 15 minutes from the first `received_at`; duplicates do not extend it.
DEDUPE_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class Admission:
    """What the Receiver decided about one delivery.

    `is_duplicate` is what the caller uses to decide whether to enqueue, so the
    enqueue decision and the database decision cannot disagree.
    """

    event_id: str
    fingerprint: str
    dedupe_count: int
    is_duplicate: bool


async def admit(
    connection: AsyncConnection,
    event: AgentEvent,
    *,
    window: timedelta = DEDUPE_WINDOW,
) -> Admission:
    """Record `event`, or count it against the open event with the same fingerprint.

    Returns the surviving event's identity either way, so a duplicate delivery is
    traceable to the incident it joined rather than being silently dropped.

    The caller must run this inside a transaction: the advisory lock below is
    transaction-scoped, so committing is what releases it.
    """
    cutoff = event.received_at - window

    # Serialize deliveries of this fingerprint for the rest of the transaction.
    # `hashtext` is stable within a major version, and a collision would only
    # make two unrelated incidents wait for each other, never merge them — the
    # fingerprint equality check below is what decides identity.
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:fingerprint))"),
        {"fingerprint": event.fingerprint},
    )

    updated = (
        await connection.execute(
            text(
                """
                UPDATE events
                   SET dedupe_count = dedupe_count + 1
                 WHERE id = (
                       SELECT id FROM events
                        WHERE fingerprint = :fingerprint
                          AND quarantined = false
                          AND received_at > :cutoff
                        ORDER BY received_at
                        LIMIT 1
                 )
             RETURNING id, dedupe_count
                """
            ),
            {"fingerprint": event.fingerprint, "cutoff": cutoff},
        )
    ).first()

    if updated is not None:
        return Admission(
            event_id=str(updated.id),
            fingerprint=event.fingerprint,
            dedupe_count=int(updated.dedupe_count),
            is_duplicate=True,
        )

    await connection.execute(
        text(
            """
            INSERT INTO events
                   (id, source, fingerprint, received_at, dedupe_count,
                    quarantined, quarantine_reason, payload)
            VALUES (:id, :source, :fingerprint, :received_at, 1,
                    false, NULL, CAST(:payload AS jsonb))
            """
        ),
        {
            "id": event.id,
            "source": event.source.value,
            "fingerprint": event.fingerprint,
            "received_at": event.received_at,
            # The AgentEvent, not the vendor body: `payload` is the normalized
            # index. The raw body's home is the JSONL audit record (SPEC 5.8).
            "payload": event.model_dump_json(),
        },
    )
    return Admission(
        event_id=str(event.id),
        fingerprint=event.fingerprint,
        dedupe_count=1,
        is_duplicate=False,
    )


async def quarantine(
    connection: AsyncConnection,
    *,
    event_id: str,
    source: str,
    received_at: datetime,
    reason: str,
) -> None:
    """Record a delivery that could not be normalized.

    Kept as a row with no payload and no fingerprint, which is the only shape the
    table's check constraint allows for a quarantined event. The row exists so an
    operator can see that something arrived and was rejected; the body itself is
    in the audit record.
    """
    await connection.execute(
        text(
            """
            INSERT INTO events
                   (id, source, fingerprint, received_at, dedupe_count,
                    quarantined, quarantine_reason, payload)
            VALUES (:id, :source, NULL, :received_at, 1, true, :reason, NULL)
            """
        ),
        {"id": event_id, "source": source, "received_at": received_at, "reason": reason},
    )


async def close_window(connection: AsyncConnection, *, fingerprint: str) -> int:
    """Close the open dedupe window for `fingerprint`, returning rows affected.

    SPEC 5.1: an incident close also closes the window. Without this a recovery
    followed by a genuine re-trigger inside 15 minutes would be counted as a
    duplicate of the incident that just ended.
    """
    result = await connection.execute(
        text(
            """
            UPDATE events
               SET received_at = received_at - INTERVAL '15 minutes'
             WHERE fingerprint = :fingerprint
               AND quarantined = false
            """
        ),
        {"fingerprint": fingerprint},
    )
    return result.rowcount
