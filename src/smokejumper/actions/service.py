"""Deterministic actions on a Conclusion (SPEC 5.6). No model calls here.

The one promise this module keeps is **exactly one ticket per incident
fingerprint**: create the first time, update every time after. The uniqueness is
a partial unique index in migration 0003, not a check in Python, because two
workers concluding the same fingerprint concurrently would both pass an
application-level check and file two tickets.

`ON CONFLICT DO NOTHING` plus a re-read is what turns that index from an error
into correct behaviour: the loser of the race finds the winner's ticket and
updates it, which is exactly what a second delivery should do.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from smokejumper.contracts.conclusions import Conclusion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TicketOutcome:
    """What happened to the ticket for this conclusion."""

    ticket_id: str
    external_id: str
    created: bool
    update_count: int


async def apply(
    connection: AsyncConnection,
    conclusion: Conclusion,
    *,
    now: datetime | None = None,
) -> TicketOutcome:
    """Create the ticket for this fingerprint, or update the open one.

    `created` tells the caller which happened, so the audit record and the Slack
    receipt can say "opened" or "updated" truthfully rather than guessing.
    """
    moment = now or datetime.now(tz=UTC)
    ticket_id = uuid4()
    # The fixture provider issues a readable id; a real adapter would return the
    # provider's own. Derived from the fingerprint so it is stable per incident.
    external_id = f"SMOKE-{conclusion.fingerprint[:8].upper()}"

    inserted = (
        await connection.execute(
            text(
                """
                INSERT INTO tickets
                       (id, fingerprint, provider, external_id, url, created_at,
                        closed_at, update_count)
                VALUES (:id, :fingerprint, 'fixture', :external_id, NULL, :now, NULL, 0)
                ON CONFLICT (fingerprint) WHERE closed_at IS NULL DO NOTHING
             RETURNING id, external_id
                """
            ),
            {
                "id": ticket_id,
                "fingerprint": conclusion.fingerprint,
                "external_id": external_id,
                "now": moment,
            },
        )
    ).first()

    if inserted is not None:
        logger.info("opened ticket %s for %s", inserted.external_id, conclusion.fingerprint)
        return TicketOutcome(
            ticket_id=str(inserted.id),
            external_id=str(inserted.external_id),
            created=True,
            update_count=0,
        )

    # Someone already owns this fingerprint: comment on theirs.
    updated = (
        await connection.execute(
            text(
                """
                UPDATE tickets
                   SET update_count = update_count + 1
                 WHERE fingerprint = :fingerprint
                   AND closed_at IS NULL
             RETURNING id, external_id, update_count
                """
            ),
            {"fingerprint": conclusion.fingerprint},
        )
    ).first()

    if updated is None:  # pragma: no cover - only if the row closed mid-transaction
        raise RuntimeError(
            f"no open ticket for {conclusion.fingerprint} after a conflicting insert"
        )

    logger.info(
        "updated ticket %s for %s (update #%d)",
        updated.external_id,
        conclusion.fingerprint,
        updated.update_count,
    )
    return TicketOutcome(
        ticket_id=str(updated.id),
        external_id=str(updated.external_id),
        created=False,
        update_count=int(updated.update_count),
    )


async def open_run(
    connection: AsyncConnection,
    *,
    run_id: UUID,
    event_id: UUID,
    fingerprint: str,
    audit_log_file: str,
    audit_start_offset: int,
    started_at: datetime,
) -> None:
    """Record that a run began, before any work happens.

    Written first so a crash mid-investigation leaves a `running` row rather than
    no trace: an incident that vanished is indistinguishable from one that never
    arrived.
    """
    await connection.execute(
        text(
            """
            INSERT INTO runs
                   (run_id, event_id, fingerprint, status, started_at,
                    audit_log_file, audit_start_offset)
            VALUES (:run_id, :event_id, :fingerprint, 'running', :started_at,
                    :audit_log_file, :audit_start_offset)
            """
        ),
        {
            "run_id": run_id,
            "event_id": event_id,
            "fingerprint": fingerprint,
            "started_at": started_at,
            "audit_log_file": audit_log_file,
            "audit_start_offset": audit_start_offset,
        },
    )


async def close_run(
    connection: AsyncConnection,
    *,
    run_id: UUID,
    status: str,
    conclusion: Conclusion | None,
    audit_end_offset: int,
) -> None:
    """Record the run's outcome and the byte range replay must read."""
    await connection.execute(
        text(
            """
            UPDATE runs
               SET status = :status,
                   conclusion = CAST(:conclusion AS jsonb),
                   finished_at = :finished_at,
                   audit_end_offset = :audit_end_offset
             WHERE run_id = :run_id
            """
        ),
        {
            "run_id": run_id,
            "status": status,
            "conclusion": conclusion.model_dump_json() if conclusion else None,
            "finished_at": datetime.now(tz=UTC),
            "audit_end_offset": audit_end_offset,
        },
    )
