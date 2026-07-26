"""B4 — `ToolCall` / `ToolResult` (SPEC §4)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from smokejumper.contracts.base import Contract


class ToolTier(StrEnum):
    """Read tier executes; privileged tier suspends the run for approval (B5)."""

    READ = "read"
    PRIVILEGED = "privileged"


class ToolCall(Contract):
    run_id: UUID
    agent: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    args: dict[str, JsonValue] = Field(default_factory=dict)
    tier: ToolTier


class ToolResult(Contract):
    """The outcome of one tool call.

    `cost` is `Decimal` and required: the per-run spend ledger is authoritative
    and fails closed, which it cannot do if a call may report no price or a price
    that drifted through binary floating point.
    """

    ok: bool
    value: JsonValue = None
    error: str | None = None
    latency_ms: int = Field(ge=0)
    cost: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> ToolResult:
        if (self.value is None) == (self.error is None):
            raise ValueError("ToolResult carries exactly one of `value` or `error`")
        if self.ok != (self.error is None):
            raise ValueError(
                "`ok` must agree with the outcome: True with `value`, False with `error`"
            )
        return self
