"""B6 — `Conclusion`, the determinism boundary (SPEC §4)."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from smokejumper.contracts.assignments import Finding
from smokejumper.contracts.base import Contract, Sha256Hex


class ConclusionStatus(StrEnum):
    ROOT_CAUSED = "root_caused"
    MITIGATED = "mitigated"
    INCONCLUSIVE = "inconclusive"
    NEEDS_HUMAN = "needs_human"


class Conclusion(Contract):
    """What the run concluded, and the receipts for it.

    Nothing downstream of a `Conclusion` may call a model, so this is the last
    non-deterministic artifact in a run: Actions read it and do arithmetic.
    A budget breach or a provider outage still produces one of these
    (`inconclusive` / `needs_human`) — a run never dies silently.
    """

    run_id: UUID
    fingerprint: Sha256Hex
    status: ConclusionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    summary_md: str
    findings: list[Finding] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    proposed_actions: list[str] = Field(default_factory=list)
    tokens_spent: int = Field(ge=0)
    wall_ms: int = Field(ge=0)
