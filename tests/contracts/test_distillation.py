"""B9 — `DistillationCandidate`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from smokejumper.contracts import DistillationCandidate

RUN_ID = "0192f0a1-0000-7000-8000-000000000001"
FINGERPRINT = "779f0b514e31fc4b83fa0d1dcad8c3498fe929e0c2a86b43d05bd4a41bda5e86"
CANDIDATE: dict[str, object] = {
    "run_id": RUN_ID,
    "fingerprint": FINGERPRINT,
    "conclusion": {
        "run_id": RUN_ID,
        "fingerprint": FINGERPRINT,
        "status": "root_caused",
        "confidence": 0.82,
        "summary_md": "Deploy raised checkout 5xx.",
        "findings": [],
        "evidence_refs": ["prom:rate(http_errors[5m])@1720000000"],
        "proposed_actions": [],
        "tokens_spent": 18400,
        "wall_ms": 42_000,
    },
    "closed_at": "2026-07-26T17:12:00Z",
}


def test_candidate_round_trips_json() -> None:
    candidate = DistillationCandidate.model_validate(CANDIDATE)
    assert DistillationCandidate.model_validate_json(candidate.model_dump_json()) == candidate


def test_a_candidate_carries_the_conclusion_it_was_distilled_from() -> None:
    with pytest.raises(ValidationError):
        DistillationCandidate.model_validate(
            {"run_id": RUN_ID, "fingerprint": FINGERPRINT, "closed_at": "2026-07-26T17:12:00Z"}
        )
