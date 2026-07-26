"""B11 — `Assignment` / `Finding`, the supervisor↔specialist boundary (SPEC §4)."""

from __future__ import annotations

from pydantic import Field

from smokejumper.contracts.base import Contract


class Budget(Contract):
    """A specialist's allowance, and — as `budget_spent` — what it actually used."""

    tool_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)


class Assignment(Contract):
    """One question handed to one specialist.

    `context_slice` is the only context the specialist gets: sub-agents are
    stateless, with no memory between runs (SPEC §5.3).
    """

    agent: str = Field(min_length=1)
    question: str = Field(min_length=1)
    context_slice: str
    budget: Budget


class Finding(Contract):
    agent: str = Field(min_length=1)
    hypothesis: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    budget_spent: Budget
