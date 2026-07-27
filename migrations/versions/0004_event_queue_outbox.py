"""Durable event delivery, retry-idempotent fixture actions, and recovery closure.

Revision ID: 0004_event_queue_outbox
Revises: 0003_runs_and_tickets

The normalized event row is the outbox record: admission commits before Redis
publication, and `queued_at` remains NULL until XADD succeeds. A background
dispatcher retries NULL rows, closing the crash window between Postgres and Redis.
The action ledger suppresses ticket writes on Redis redelivery, and the recovery
trigger closes the open fixture ticket with its event window.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_event_queue_outbox"
down_revision: str | None = "0003_runs_and_tickets"


def upgrade() -> None:
    op.add_column("events", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("queue_message_id", sa.Text(), nullable=True))

    # Existing rows predate the outbox contract and were already offered to the
    # stream by the old synchronous path. Do not replay them during migration.
    op.execute(
        """
        UPDATE events
           SET queued_at = received_at,
               queue_message_id = 'legacy-before-0004'
         WHERE quarantined = false
        """
    )
    op.create_check_constraint(
        "events_queue_state_paired",
        "events",
        "(queued_at IS NULL) = (queue_message_id IS NULL)",
    )
    op.create_index(
        "ix_events_pending_queue",
        "events",
        ["received_at"],
        postgresql_where=sa.text("quarantined = false AND queued_at IS NULL"),
    )

    # One durable result per queued event/run. A Redis redelivery reuses the
    # event UUID as run_id and reads this row instead of repeating a ticket write.
    op.create_table(
        "ticket_actions",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.run_id"), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("created", sa.Boolean(), nullable=False),
        sa.Column("update_count", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Closing an event window is the incident-lifecycle fact. Keep the matching
    # fixture ticket in the same transaction without importing Actions into the
    # Receiver or relying on a later queue delivery to make recovery visible.
    op.execute(
        """
        CREATE FUNCTION smokejumper_close_ticket_on_window() RETURNS trigger AS $$
        BEGIN
            IF OLD.window_closed_at IS NULL AND NEW.window_closed_at IS NOT NULL THEN
                UPDATE tickets
                   SET closed_at = NEW.window_closed_at
                 WHERE fingerprint = NEW.fingerprint
                   AND closed_at IS NULL;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER events_close_ticket_on_window
        AFTER UPDATE OF window_closed_at ON events
        FOR EACH ROW EXECUTE FUNCTION smokejumper_close_ticket_on_window()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER events_close_ticket_on_window ON events")
    op.execute("DROP FUNCTION smokejumper_close_ticket_on_window()")
    op.drop_table("ticket_actions")
    op.drop_index("ix_events_pending_queue", table_name="events")
    op.drop_constraint("events_queue_state_paired", "events", type_="check")
    op.drop_column("events", "queue_message_id")
    op.drop_column("events", "queued_at")
