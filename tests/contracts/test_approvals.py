"""B5 — `ApprovalRequest` / `ApprovalDecision`."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from smokejumper.contracts import ApprovalDecision, ApprovalRequest

RUN_ID = "0192f0a1-0000-7000-8000-000000000001"
PRIVILEGED_CALL: dict[str, object] = {
    "run_id": RUN_ID,
    "agent": "metrics-analyst",
    "tool": "demo_destructive_noop",
    "args": {},
    "tier": "privileged",
}


def make_request(**overrides: object) -> ApprovalRequest:
    payload: dict[str, object] = {
        "id": "0192f0a1-0000-7000-8000-0000000000a1",
        "run_id": RUN_ID,
        "channel_id": "C0123456789",
        "message_ts": "1720000000.000200",
        "thread_ts": "1720000000.000100",
        "tool_call": PRIVILEGED_CALL,
        "tool_call_sha256": "c" * 64,
        "reason": "would restart the checkout deployment",
        "requested_at": "2026-07-26T17:00:00Z",
        "expires_at": "2026-07-26T17:30:00Z",
    }
    return ApprovalRequest.model_validate(payload | overrides)


def test_approval_request_round_trips_json() -> None:
    request = make_request()
    assert ApprovalRequest.model_validate_json(request.model_dump_json()) == request


def test_a_read_tier_call_cannot_enter_the_approval_path() -> None:
    """Only the privileged tier suspends a run; routing a read call through
    approval would give it a human signature it never needed."""
    with pytest.raises(ValidationError, match="privileged"):
        make_request(tool_call=PRIVILEGED_CALL | {"tier": "read"})


def test_expiry_must_be_after_the_request() -> None:
    with pytest.raises(ValidationError, match="after requested_at"):
        make_request(expires_at="2026-07-26T17:00:00Z")


def test_tool_call_hash_must_be_sha256_hex() -> None:
    with pytest.raises(ValidationError):
        make_request(tool_call_sha256="not-a-hash")


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_request(requested_at=datetime(2026, 7, 26, 17, 0, 0))


def test_decision_round_trips_json() -> None:
    decision = ApprovalDecision.model_validate(
        {
            "approved": True,
            "decided_by": "U0123456789",
            "decided_at": "2026-07-26T17:04:00Z",
            "token": "3f7c0c1e9b1d4a2f8e6c5b4a39281706f5e4d3c2b1a09f8e7d6c5b4a39281706",
        }
    )
    assert ApprovalDecision.model_validate_json(decision.model_dump_json()) == decision


def test_a_decision_without_a_token_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ApprovalDecision.model_validate(
            {
                "approved": True,
                "decided_by": "U0123456789",
                "decided_at": "2026-07-26T17:04:00Z",
                "token": "",
            }
        )
