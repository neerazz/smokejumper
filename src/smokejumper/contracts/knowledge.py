"""B3 — the `KnowledgeBundle` returned by `retrieve(ctx)` (SPEC §4)."""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from smokejumper.contracts.base import Contract


class KnowledgeItem(Contract):
    """One retrieved item.

    `valid_at` is when the fact held in the world; `recorded_at` is when we came
    to believe it. Retrieval defaults to currently-valid, and replay can ask what
    was believed at time T — which only works if both are carried per item.
    """

    content: str
    source_ref: str = Field(min_length=1)
    valid_at: AwareDatetime
    recorded_at: AwareDatetime
    score: float


class KnowledgeBundle(Contract):
    """Everything retrieval found, grouped by where it came from.

    `graph_paths` stays empty in v1: the bi-temporal edge tables and ≤2-hop
    expansion are deferred behind `MemoryPort`, and the field is kept because the
    boundary shape must not change when they land.
    """

    episodes: list[KnowledgeItem] = Field(default_factory=list)
    graph_paths: list[KnowledgeItem] = Field(default_factory=list)
    recipes: list[KnowledgeItem] = Field(default_factory=list)
    federated: list[KnowledgeItem] = Field(default_factory=list)
    tokens_used: int = Field(ge=0)
