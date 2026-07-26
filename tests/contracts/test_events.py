"""B2 — `AgentEvent`."""

from __future__ import annotations

import hashlib
from datetime import datetime

import pytest
from pydantic import ValidationError

from smokejumper.contracts import AgentEvent, event_fingerprint

FINGERPRINT = event_fingerprint("grafana", "alert-42", [("service", "checkout"), ("host", "web-1")])


def make_event(**overrides: object) -> AgentEvent:
    payload: dict[str, object] = {
        "id": "0192f0a1-0000-7000-8000-000000000001",
        "source": "grafana",
        "kind": "alert",
        "source_event_key": "alert-42",
        "fingerprint": FINGERPRINT,
        "severity": "high",
        "title": "Checkout error rate above 5%",
        "body": "sum(rate(http_errors[5m])) / sum(rate(http_requests[5m])) > 0.05",
        "entities": [{"type": "service", "id": "checkout"}, {"type": "host", "id": "web-1"}],
        "occurred_at": "2026-07-26T17:00:00Z",
        "received_at": "2026-07-26T17:00:05Z",
        "raw": {"state": "alerting", "values": {"B": 0.07}, "labels": None},
    }
    return AgentEvent.model_validate(payload | overrides)


def test_agent_event_round_trips_json() -> None:
    event = make_event()
    assert AgentEvent.model_validate_json(event.model_dump_json()) == event
    assert event.model_dump()["schema_version"] == 1


def test_renaming_the_title_does_not_change_the_fingerprint() -> None:
    reworded = make_event(title="Checkout 5xx ratio breached its threshold", body="different text")
    assert reworded.fingerprint == make_event().fingerprint


def test_entity_order_in_the_event_does_not_change_the_accepted_fingerprint() -> None:
    reordered = make_event(
        entities=[{"type": "host", "id": "web-1"}, {"type": "service", "id": "checkout"}]
    )
    assert reordered.fingerprint == FINGERPRINT


def test_a_fingerprint_taken_over_the_title_is_rejected() -> None:
    title_hash = hashlib.sha256(b"Checkout error rate above 5%").hexdigest()
    with pytest.raises(ValidationError, match="canonical hash"):
        make_event(fingerprint=title_hash)


def test_a_fingerprint_that_ignores_an_entity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="canonical hash"):
        make_event(fingerprint=event_fingerprint("grafana", "alert-42", [("service", "checkout")]))


def test_fingerprint_must_be_lowercase_sha256_hex() -> None:
    with pytest.raises(ValidationError):
        make_event(fingerprint=FINGERPRINT.upper())


@pytest.mark.parametrize("field", ["occurred_at", "received_at"])
def test_naive_timestamps_are_rejected_not_coerced(field: str) -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_event(**{field: datetime(2026, 7, 26, 17, 0, 0)})


@pytest.mark.parametrize(
    ("field", "value"),
    [("source", "nagios"), ("kind", "incident"), ("severity", "sev1")],
)
def test_enums_are_closed(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_event(**{field: value})


def test_dedupe_count_starts_at_one_and_cannot_be_zero() -> None:
    assert make_event().dedupe_count == 1
    with pytest.raises(ValidationError):
        make_event(dedupe_count=0)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match=r"extra_forbidden|Extra inputs"):
        make_event(sevirity="high")


def test_missing_identity_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentEvent.model_validate({"source": "grafana", "kind": "alert"})
