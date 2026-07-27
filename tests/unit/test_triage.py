"""Deterministic triage preserves the worker's B6 run identity."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from smokejumper.contracts.events import AgentEvent, EventKind, EventSource, Severity
from smokejumper.contracts.fingerprint import event_fingerprint
from smokejumper.intelligence.triage import triage


def test_explicit_run_id_reaches_the_conclusion() -> None:
    run_id = uuid4()
    key = "monitor-1"
    event = AgentEvent(
        schema_version=1,
        id=uuid4(),
        source=EventSource.GENERIC,
        kind=EventKind.ALERT,
        source_event_key=key,
        fingerprint=event_fingerprint("generic", key, []),
        severity=Severity.HIGH,
        title="canary failed",
        body="",
        occurred_at=datetime(2026, 7, 26, tzinfo=UTC),
        received_at=datetime(2026, 7, 26, tzinfo=UTC),
    )

    conclusion = triage(event, run_id=run_id)

    assert conclusion.run_id == run_id
    assert conclusion.run_id != event.id
