"""Receiver persistence and queue publication form one admission attempt."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from smokejumper.contracts.events import AgentEvent, EventKind, EventSource, Severity
from smokejumper.contracts.fingerprint import event_fingerprint
from smokejumper.receiver import delivery, repository
from smokejumper.receiver import routes as receiver_routes


class _Transaction:
    def __init__(self) -> None:
        self.connection = object()
        self.exit_exception: type[BaseException] | None = None
        self.exited = False

    async def __aenter__(self) -> object:
        return self.connection

    async def __aexit__(self, exc_type: type[BaseException] | None, *_: object) -> None:
        self.exit_exception = exc_type
        self.exited = True


class _Engine:
    def __init__(self, transaction: _Transaction) -> None:
        self.transaction = transaction

    def begin(self) -> _Transaction:
        return self.transaction


def _event() -> AgentEvent:
    key = "delivery-atomicity"
    return AgentEvent(
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


async def test_publish_failure_leaves_a_durable_pending_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis failure happens after commit and is retried from the durable row."""
    event = _event()
    transaction = _Transaction()
    admission = repository.Admission(
        event_id=str(event.id),
        fingerprint=event.fingerprint,
        dedupe_count=1,
        is_duplicate=False,
    )
    monkeypatch.setattr(receiver_routes.repository, "admit", AsyncMock(return_value=admission))

    async def fail_after_commit(*_: object, **__: object) -> None:
        assert transaction.exited, "admission must commit before Redis is touched"
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        receiver_routes.delivery,
        "dispatch_event",
        AsyncMock(side_effect=fail_after_commit),
    )

    result = await receiver_routes._admit_and_publish_one(
        engine=_Engine(transaction),  # type: ignore[arg-type]
        redis=object(),  # type: ignore[arg-type]
        event=event,
    )

    assert transaction.exit_exception is None
    assert result["status"] == "accepted"
    assert result["queue_status"] == "pending"
    assert result["queue_message_id"] is None


async def test_dispatch_records_the_redis_receipt_in_the_same_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _event()
    transaction = _Transaction()
    mark = AsyncMock()
    monkeypatch.setattr(
        delivery.repository,
        "event_for_queue",
        AsyncMock(return_value=(event, None)),
    )
    monkeypatch.setattr(delivery.repository, "mark_queued", mark)
    monkeypatch.setattr(delivery.producer, "publish", AsyncMock(return_value="171-0"))

    message_id = await delivery.dispatch_event(
        _Engine(transaction),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        event_id=str(event.id),
    )

    assert message_id == "171-0"
    mark.assert_awaited_once()
    assert mark.await_args is not None
    assert mark.await_args.kwargs["event_id"] == str(event.id)
    assert mark.await_args.kwargs["message_id"] == "171-0"


async def test_dispatch_failure_does_not_mark_the_event_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _event()
    transaction = _Transaction()
    mark = AsyncMock()
    monkeypatch.setattr(
        delivery.repository,
        "event_for_queue",
        AsyncMock(return_value=(event, None)),
    )
    monkeypatch.setattr(delivery.repository, "mark_queued", mark)
    monkeypatch.setattr(
        delivery.producer,
        "publish",
        AsyncMock(side_effect=RuntimeError("redis unavailable")),
    )

    with pytest.raises(RuntimeError, match="redis unavailable"):
        await delivery.dispatch_event(
            _Engine(transaction),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            event_id=str(event.id),
        )

    assert transaction.exit_exception is RuntimeError
    mark.assert_not_awaited()
