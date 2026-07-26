"""B6 — `Conclusion` — and the B11 `Finding`/`Assignment` it aggregates."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from smokejumper.contracts import Assignment, Conclusion, ConclusionStatus, Finding

RUN_ID = "0192f0a1-0000-7000-8000-000000000001"
FINGERPRINT = "779f0b514e31fc4b83fa0d1dcad8c3498fe929e0c2a86b43d05bd4a41bda5e86"
FINDING: dict[str, object] = {
    "agent": "metrics-analyst",
    "hypothesis": "checkout 5xx follows the 17:00 deploy",
    "evidence": ["prom:rate(http_errors[5m])@1720000000"],
    "confidence": 0.8,
    "budget_spent": {"tool_calls": 3, "tokens": 8200},
}


def make_conclusion(**overrides: object) -> Conclusion:
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "fingerprint": FINGERPRINT,
        "status": "root_caused",
        "confidence": 0.82,
        "summary_md": "Deploy `web-1@a1b2c3` raised checkout 5xx from 0.2% to 7%.",
        "findings": [FINDING],
        "evidence_refs": ["prom:rate(http_errors[5m])@1720000000", "linear:SMOKE-123"],
        "proposed_actions": ["roll back web-1 to the previous revision"],
        "tokens_spent": 18400,
        "wall_ms": 42_000,
    }
    return Conclusion.model_validate(payload | overrides)


def test_conclusion_round_trips_json() -> None:
    conclusion = make_conclusion()
    assert Conclusion.model_validate_json(conclusion.model_dump_json()) == conclusion
    assert conclusion.status is ConclusionStatus.ROOT_CAUSED


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 2])
def test_confidence_is_bounded_zero_to_one(confidence: float) -> None:
    with pytest.raises(ValidationError):
        make_conclusion(confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_confidence_bounds_are_inclusive(confidence: float) -> None:
    assert make_conclusion(confidence=confidence).confidence == confidence


def test_status_enum_is_closed() -> None:
    with pytest.raises(ValidationError):
        make_conclusion(status="probably_fine")


def test_counters_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        make_conclusion(tokens_spent=-1)
    with pytest.raises(ValidationError):
        make_conclusion(wall_ms=-1)


def test_a_finding_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate(FINDING | {"confidence": 1.5})


def test_a_budget_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        Assignment.model_validate(
            {
                "agent": "log-analyst",
                "question": "which service started erroring first?",
                "context_slice": "checkout, 16:50-17:10",
                "budget": {"tool_calls": -1, "tokens": 50_000},
            }
        )


def test_an_assignment_round_trips_json() -> None:
    assignment = Assignment.model_validate(
        {
            "agent": "log-analyst",
            "question": "which service started erroring first?",
            "context_slice": "checkout, 16:50-17:10",
            "budget": {"tool_calls": 8, "tokens": 50_000},
        }
    )
    assert Assignment.model_validate_json(assignment.model_dump_json()) == assignment
