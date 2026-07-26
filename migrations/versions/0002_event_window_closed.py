"""Close the dedupe window with explicit state instead of a falsified timestamp.

Revision ID: 0002_event_window_closed
Revises: 0001_core_tables

`close_window` previously faked expiry by subtracting 15 minutes from
`received_at`. That worked for the dedupe query and was wrong in three ways:
it falsified an audit field (`received_at` is when we actually saw the alert),
it drifted further backwards on every recovery because nothing made the
subtraction idempotent, and it left the column disagreeing with the
`received_at` inside the stored `AgentEvent` payload.

State belongs in its own column. `window_closed_at` is NULL while the window is
open, and the timestamp of the recovery once it is closed, so the row records
*both* facts truthfully instead of encoding one by corrupting the other.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_event_window_closed"
down_revision: str | None = "0001_core_tables"


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("window_closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The Receiver's hot query is "is there an open event for this fingerprint",
    # which is now fingerprint + open + inside the window. Partial on the open
    # rows because closed ones are never candidates and only add index bloat.
    op.create_index(
        "ix_events_open_window",
        "events",
        ["fingerprint", "received_at"],
        postgresql_where=sa.text("window_closed_at IS NULL AND quarantined = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_events_open_window", table_name="events")
    op.drop_column("events", "window_closed_at")
