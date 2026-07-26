"""B4 — `ToolCall` / `ToolResult`."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from smokejumper.contracts import ToolCall, ToolResult, ToolTier

RUN_ID = "0192f0a1-0000-7000-8000-000000000001"


def make_result(**overrides: object) -> ToolResult:
    payload: dict[str, object] = {
        "ok": True,
        "value": {"series": [[1720000000, "0.07"]]},
        "latency_ms": 42,
        "cost": "0",
    }
    return ToolResult.model_validate(payload | overrides)


def test_tool_call_round_trips_json() -> None:
    call = ToolCall.model_validate(
        {
            "run_id": RUN_ID,
            "agent": "metrics-analyst",
            "tool": "metric.query",
            "args": {"query": "rate(http_errors[5m])", "step": 60},
            "tier": "read",
        }
    )
    assert ToolCall.model_validate_json(call.model_dump_json()) == call
    assert call.tier is ToolTier.READ


def test_tier_enum_is_closed() -> None:
    with pytest.raises(ValidationError):
        ToolCall.model_validate(
            {"run_id": RUN_ID, "agent": "a", "tool": "t", "args": {}, "tier": "admin"}
        )


def test_a_successful_result_carries_a_value() -> None:
    assert make_result().error is None


def test_a_failed_result_carries_an_error() -> None:
    failed = make_result(ok=False, value=None, error="prometheus returned 503")
    assert failed.value is None


def test_both_outcomes_at_once_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        make_result(error="also failed")


def test_neither_outcome_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        make_result(value=None)


@pytest.mark.parametrize(
    "outcome",
    [
        {"ok": False, "value": {"data": 1}, "error": None},
        {"ok": True, "value": None, "error": "boom"},
    ],
)
def test_ok_must_agree_with_the_outcome(outcome: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="must agree"):
        make_result(**outcome)


def test_cost_stays_exact_through_json() -> None:
    """The spend ledger is money: a cost that round-trips through a float has
    already lost the property the ceiling is enforced on."""
    priced = make_result(cost="0.0001234")
    restored = ToolResult.model_validate_json(priced.model_dump_json())
    assert restored.cost == Decimal("0.0001234")
    assert isinstance(restored.cost, Decimal)


def test_cost_and_latency_are_required_and_non_negative() -> None:
    with pytest.raises(ValidationError):
        ToolResult.model_validate({"ok": True, "value": 1, "latency_ms": 10})
    with pytest.raises(ValidationError):
        make_result(cost="-0.01")
    with pytest.raises(ValidationError):
        make_result(latency_ms=-1)
