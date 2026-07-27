"""Queue acknowledgement and redelivery boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from smokejumper import worker
from smokejumper.contracts.events import AgentEvent, EventKind, EventSource, Severity
from smokejumper.contracts.fingerprint import event_fingerprint


def _event() -> AgentEvent:
    key = "worker-ack-boundary"
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


async def test_success_is_acked_only_after_handle_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _event()
    order: list[str] = []

    async def handled(*_: object) -> str:
        order.append("committed")
        return "needs_human"

    redis = AsyncMock()
    redis.xack.side_effect = lambda *_: order.append("acked")
    monkeypatch.setattr(worker, "handle", AsyncMock(side_effect=handled))

    await worker._process(  # pyright: ignore[reportPrivateUsage]
        object(),  # type: ignore[arg-type]
        redis,
        object(),  # type: ignore[arg-type]
        "1-0",
        {"event": event.model_dump_json()},
    )

    assert order == ["committed", "acked"]


async def test_processing_failure_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _event()
    redis = AsyncMock()
    monkeypatch.setattr(
        worker,
        "handle",
        AsyncMock(side_effect=RuntimeError("database commit failed")),
    )

    await worker._process(  # pyright: ignore[reportPrivateUsage]
        object(),  # type: ignore[arg-type]
        redis,
        object(),  # type: ignore[arg-type]
        "1-0",
        {"event": event.model_dump_json()},
    )

    redis.xack.assert_not_awaited()


async def test_poison_message_is_acked_to_unblock_the_stream() -> None:
    redis = AsyncMock()

    await worker._process(  # pyright: ignore[reportPrivateUsage]
        object(),  # type: ignore[arg-type]
        redis,
        object(),  # type: ignore[arg-type]
        "1-0",
        {"event": "not json"},
    )

    redis.xack.assert_awaited_once_with(worker.STREAM, worker.GROUP, "1-0")
