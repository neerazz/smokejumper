"""M0 core tables: the pgvector extension, `events`, and `runs`.

Revision ID: 0001_core_tables
Revises: None

Scope is deliberately narrow (SPEC 7). `approvals`, `tickets`, and `episodes`
arrive with the milestones that write them, and graph tables are out of v1
scope; a table created before its writer exists is a schema nobody can verify.

The `vector` extension is enabled here rather than alongside the M3 `episodes`
table because `CREATE EXTENSION` needs privileges the application role may not
hold in dev or prod. Requesting them once, at bootstrap, is easier to review and
grant than twice.

`events` is one table with a quarantine flag rather than two tables. A
quarantined row is precisely an inbound payload that could not be normalized to
an `AgentEvent` (SPEC 5.1), so it has no `payload` and no `fingerprint`; the
check constraint makes that the only legal shape instead of a convention. The
raw body stays in the JSONL audit record, which is the source of truth for
payloads (SPEC 5.8) — Postgres holds the index, not the evidence.

`runs.status` has no check constraint: SPEC 7 names the column but never
enumerates the run lifecycle. M2 owns the lifecycle and adds the constraint with
the values it actually writes, rather than this migration inventing them.

LangGraph checkpoint tables are NOT Alembic-managed. `PostgresSaver.setup()`
owns them. Their schema is internal to `langgraph-checkpoint-postgres` and
changes with its version, so a hand-copied Alembic version would collide with
the library's own setup the first time either side moved. SPEC 7 lists
`checkpoints` in the data model without saying who creates it; this is that
decision, and M2 must call `setup()` at boot rather than add a migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core_tables"
down_revision: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dedupe_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("quarantined", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("quarantine_reason", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "source IN ('grafana', 'alertmanager', 'datadog', 'pagerduty',"
            " 'generic', 'slack', 'scheduled')",
            name="events_source_known",
        ),
        sa.CheckConstraint(
            "quarantined = (payload IS NULL)"
            " AND quarantined = (fingerprint IS NULL)"
            " AND quarantined = (quarantine_reason IS NOT NULL)",
            name="events_quarantine_invariant",
        ),
    )
    # The dedupe window is a lookup by fingerprint bounded by time (SPEC 5.1),
    # which is the one query the Receiver runs on every inbound alert.
    op.create_index(
        "ix_events_fingerprint_received_at",
        "events",
        ["fingerprint", "received_at"],
    )

    op.create_table(
        "runs",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_log_file", sa.Text(), nullable=False),
        sa.Column("audit_start_offset", sa.BigInteger(), nullable=False),
        sa.Column("audit_end_offset", sa.BigInteger(), nullable=True),
        # An end offset below the start offset would send replay into another
        # run's events, silently and unrepeatably. NULL means the run is open.
        sa.CheckConstraint(
            "audit_end_offset IS NULL OR audit_end_offset >= audit_start_offset",
            name="runs_audit_offsets_ordered",
        ),
    )
    op.create_index("ix_runs_fingerprint", "runs", ["fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_runs_fingerprint", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_events_fingerprint_received_at", table_name="events")
    op.drop_table("events")
    op.execute("DROP EXTENSION IF EXISTS vector")
