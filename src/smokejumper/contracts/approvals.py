"""B5 — `ApprovalRequest` / `ApprovalDecision` (SPEC §4)."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from smokejumper.contracts.base import Contract, Sha256Hex
from smokejumper.contracts.tools import ToolCall, ToolTier


class ApprovalRequest(Contract):
    """A privileged tool call parked in Slack, waiting for a human.

    `tool_call_sha256` is what the minted token is bound to, together with
    `(channel_id, thread_ts)`: an approval of one call can then never be replayed
    against a different call in the same thread.
    """

    id: UUID
    run_id: UUID
    channel_id: str = Field(min_length=1)
    message_ts: str = Field(min_length=1)
    thread_ts: str = Field(min_length=1)
    tool_call: ToolCall
    tool_call_sha256: Sha256Hex
    reason: str
    requested_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def _approvable_and_expiring(self) -> ApprovalRequest:
        if self.tool_call.tier is not ToolTier.PRIVILEGED:
            raise ValueError("only a privileged ToolCall enters the approval path")
        if self.expires_at <= self.requested_at:
            raise ValueError("expires_at must be after requested_at")
        return self


class ApprovalDecision(Contract):
    """A human's answer.

    `token` is the opaque single-use value the Auth port minted; only its hash is
    stored, and consumption is one atomic update. Expiry with no decision is a
    deny, so a missing decision is never read as consent.
    """

    approved: bool
    decided_by: str = Field(min_length=1)
    decided_at: AwareDatetime
    token: str = Field(min_length=1)
