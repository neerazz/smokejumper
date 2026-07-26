"""Tickets, and the run-lifecycle columns the worker writes.

Revision ID: 0003_runs_and_tickets
Revises: 0002_event_window_closed

`runs` existed from 0001 but nothing wrote it. The worker does, so this adds the
columns a run actually needs: which event started it, the conclusion it reached,
and when it finished. `status` gets its CHECK constraint here rather than in 0001
because this is the first revision that knows the real lifecycle values.

`tickets` maps a fingerprint to exactly one open ticket. The unique index on
`(fingerprint)` for open rows is what makes "one ticket per incident" a database
guarantee instead of an application convention — a second create for the same
fingerprint raises rather than filing a duplicate.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_runs_and_tickets"
down_revision: str | None = "0002_event_window_closed"

RUN_STATUSES = ("running", "concluded", "needs_human", "failed")


def upgrade() -> None:
    op.add_column("runs", sa.Column("event_id", sa.Uuid(), nullable=True))
    op.add_column("runs", sa.Column("conclusion", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column("runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "runs_status_known",
        "runs",
        "status IN " + str(RUN_STATUSES),
    )
    # A concluded run must carry its conclusion: the pair is what replay reads,
    # and a run that says "concluded" with nothing to show is unreplayable.
    op.create_check_constraint(
        "runs_concluded_has_conclusion",
        "runs",
        "status <> 'concluded' OR conclusion IS NOT NULL",
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("update_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    # "Exactly one ticket per incident fingerprint" (SPEC 1), enforced by the
    # database. Partial so a closed incident can legitimately get a new ticket.
    op.create_index(
        "uq_tickets_open_fingerprint",
        "tickets",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tickets_open_fingerprint", table_name="tickets")
    op.drop_table("tickets")
    op.drop_constraint("runs_concluded_has_conclusion", "runs", type_="check")
    op.drop_constraint("runs_status_known", "runs", type_="check")
    op.drop_column("runs", "finished_at")
    op.drop_column("runs", "conclusion")
    op.drop_column("runs", "event_id")
