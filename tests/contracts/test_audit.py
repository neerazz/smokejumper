"""B8 — `AuditEvent`, and the `llm_call` payload replay depends on."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from smokejumper.contracts import AuditEvent, AuditKind, LlmCallPayload

RUN_ID = "0192f0a1-0000-7000-8000-000000000001"
LLM_PAYLOAD: dict[str, object] = {
    "schema_version": 1,
    "prompt_ref": "agents/metrics-analyst@v3",
    "prompt_sha256": "a" * 64,
    "model": "smokejumper-worker",
    "request_sha256": "b" * 64,
    "response": {"content": "checkout 5xx correlates with the 17:00 deploy"},
    "usage": {"schema_version": 1, "input_tokens": 1200, "output_tokens": 300},
    "cost_usd": "0.0123",
    "latency_ms": 842,
}


def make_audit_event(**overrides: object) -> AuditEvent:
    payload: dict[str, object] = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "seq": 7,
        "ts": "2026-07-26T17:00:07Z",
        "actor": "metrics-analyst",
        "kind": "llm_call",
        "payload": LLM_PAYLOAD,
    }
    return AuditEvent.model_validate(payload | overrides)


def test_audit_event_round_trips_json() -> None:
    event = make_audit_event()
    assert AuditEvent.model_validate_json(event.model_dump_json()) == event
    assert event.kind is AuditKind.LLM_CALL


@pytest.mark.parametrize("missing", sorted(LLM_PAYLOAD))
def test_an_llm_call_missing_any_attribution_field_is_rejected(missing: str) -> None:
    """A model call recorded without its prompt ref/hash, request hash, response,
    usage, cost, or latency cannot be replayed or attributed later; the recorder
    must fail at write time rather than leave a hole discovered months on."""
    incomplete = {key: value for key, value in LLM_PAYLOAD.items() if key != missing}
    with pytest.raises(ValidationError):
        make_audit_event(payload=incomplete)


def test_prompt_and_request_hashes_must_be_sha256_hex() -> None:
    with pytest.raises(ValidationError):
        make_audit_event(payload=LLM_PAYLOAD | {"prompt_sha256": "v3"})
    with pytest.raises(ValidationError):
        make_audit_event(payload=LLM_PAYLOAD | {"request_sha256": "0x1234"})


def test_llm_cost_is_decimal_and_exact() -> None:
    recorded = LlmCallPayload.model_validate(LLM_PAYLOAD | {"cost_usd": "0.00000175"})
    restored = LlmCallPayload.model_validate_json(recorded.model_dump_json())
    assert restored.cost_usd == Decimal("0.00000175")
    assert isinstance(restored.cost_usd, Decimal)


def test_additive_payload_keys_are_tolerated() -> None:
    """Redaction markers and later telemetry must not invalidate a recorded line;
    only a missing attribution field may."""
    make_audit_event(payload=LLM_PAYLOAD | {"redacted_fields": ["response"]})


def test_other_kinds_keep_an_open_payload() -> None:
    event = make_audit_event(kind="transition", payload={"from": "plan", "to": "dispatch"})
    assert event.payload == {"from": "plan", "to": "dispatch"}


def test_kind_enum_is_closed() -> None:
    with pytest.raises(ValidationError):
        make_audit_event(kind="debug")


def test_sequence_numbers_start_at_zero_and_cannot_be_negative() -> None:
    assert make_audit_event(seq=0).seq == 0
    with pytest.raises(ValidationError):
        make_audit_event(seq=-1)
