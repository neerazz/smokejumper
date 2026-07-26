"""B3 — `KnowledgeBundle`."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from smokejumper.contracts import KnowledgeBundle, KnowledgeItem

EPISODE: dict[str, object] = {
    "content": "2026-06-02: same 5xx pattern, cause was a stale connection pool",
    "source_ref": "episode:0192e0a1-0000-7000-8000-00000000f001",
    "valid_at": "2026-06-02T09:00:00Z",
    "recorded_at": "2026-06-02T09:40:00Z",
    "score": 0.71,
}


def test_bundle_round_trips_json() -> None:
    bundle = KnowledgeBundle.model_validate(
        {
            "episodes": [EPISODE],
            "recipes": [EPISODE | {"source_ref": "recipe:checkout-5xx"}],
            "tokens_used": 1240,
        }
    )
    assert KnowledgeBundle.model_validate_json(bundle.model_dump_json()) == bundle


def test_graph_paths_default_empty() -> None:
    """v1 retrieval is episodes + recipes; the graph lists exist so the boundary
    does not change shape when ≤2-hop expansion lands behind `MemoryPort`."""
    bundle = KnowledgeBundle.model_validate({"tokens_used": 0})
    assert bundle.graph_paths == []
    assert bundle.federated == []


@pytest.mark.parametrize("field", ["valid_at", "recorded_at"])
def test_both_temporal_stamps_reject_naive_datetimes(field: str) -> None:
    """Replay's question — what did we believe at time T — is unanswerable if
    either stamp has no timezone."""
    with pytest.raises(ValidationError, match="timezone"):
        KnowledgeItem.model_validate(EPISODE | {field: datetime(2026, 6, 2, 9, 0, 0)})


def test_an_item_needs_a_source_ref() -> None:
    """A retrieved item with no reference cannot appear in `evidence_refs`, which
    would make a Conclusion citing it ungroundable."""
    with pytest.raises(ValidationError):
        KnowledgeItem.model_validate(EPISODE | {"source_ref": ""})


def test_tokens_used_is_required_and_non_negative() -> None:
    with pytest.raises(ValidationError):
        KnowledgeBundle.model_validate({})
    with pytest.raises(ValidationError):
        KnowledgeBundle.model_validate({"tokens_used": -1})
