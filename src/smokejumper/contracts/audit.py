"""B8 — `AuditEvent`, the Flight Recorder line (SPEC §4, §2e)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from smokejumper.contracts.base import Contract, Sha256Hex


class AuditKind(StrEnum):
    EVENT = "event"
    TRANSITION = "transition"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    GATE = "gate"
    ACTION = "action"


class TokenUsage(Contract):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class LlmCallPayload(Contract):
    """The payload an `llm_call` audit line must carry.

    `prompt_ref` + `prompt_sha256` are what make a recorded run attributable: a
    behavior regression can be traced to a prompt version, and replay can assert
    it is running the prompt it recorded rather than today's edit of it.
    `response` is the deterministic replay fixture. `cost_usd` is `Decimal`
    because the spend ceiling is money and must not accumulate float error.
    """

    model_config = ConfigDict(extra="ignore")
    """Additive telemetry and redaction markers must not invalidate a recorded
    line; a *missing* attribution field must, which is what the fields below do."""

    prompt_ref: str = Field(min_length=1)
    prompt_sha256: Sha256Hex
    model: str = Field(min_length=1)
    request_sha256: Sha256Hex
    response: JsonValue
    usage: TokenUsage
    cost_usd: Decimal = Field(ge=0)
    latency_ms: int = Field(ge=0)


class AuditEvent(Contract):
    """One append-only line in the audit record; every block emits them.

    `payload` stays an open JSON object so one line shape serves every kind, but
    `llm_call` is checked against `LlmCallPayload` below — an unattributable model
    call must fail at write time, not at replay time months later.
    """

    run_id: UUID
    seq: int = Field(ge=0)
    ts: AwareDatetime
    actor: str = Field(min_length=1)
    kind: AuditKind
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _llm_calls_are_attributable(self) -> AuditEvent:
        if self.kind is AuditKind.LLM_CALL:
            LlmCallPayload.model_validate(self.payload)
        return self
