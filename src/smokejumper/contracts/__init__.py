"""Boundary contracts B1-B11 (SPEC §4) — the source of truth for every payload.

This package is the bottom of the dependency graph: it imports nothing else from
`smokejumper`, and everything else imports it. `tests/architecture/` enforces that
mechanically.

The boundaries, and the module each lives in:

- **B1** `VerifiedInbound` — `inbound.py`
- **B2** `AgentEvent` — `events.py` (identity hashing in `fingerprint.py`)
- **B3** `KnowledgeBundle` — `knowledge.py`
- **B4** `ToolCall` / `ToolResult` — `tools.py`
- **B5** `ApprovalRequest` / `ApprovalDecision` — `approvals.py`
- **B6** `Conclusion` — `conclusions.py`
- **B7** — *intentionally unassigned.* Nothing is missing here: the number is
  reserved to keep the historical numbering from the architecture diagram, and
  reusing it would silently renumber every earlier reference to B8-B11.
- **B8** `AuditEvent` — `audit.py`
- **B9** `DistillationCandidate` — `distillation.py`
- **B10** `PlatformPort` — an *interface*, not a payload; it lives in
  `smokejumper.ports.platform`, so this package defines no B10 model.
- **B11** `Assignment` / `Finding` — `assignments.py`

`ticketing.py` additionally holds the provider-neutral ticket models §5.6 assigns
to contracts rather than to an adapter.
"""

from __future__ import annotations

from smokejumper.contracts.approvals import ApprovalDecision, ApprovalRequest
from smokejumper.contracts.assignments import Assignment, Budget, Finding
from smokejumper.contracts.audit import AuditEvent, AuditKind, LlmCallPayload, TokenUsage
from smokejumper.contracts.base import Contract, Sha256Hex
from smokejumper.contracts.conclusions import Conclusion, ConclusionStatus
from smokejumper.contracts.distillation import DistillationCandidate
from smokejumper.contracts.events import (
    AgentEvent,
    Entity,
    EventKind,
    EventSource,
    Severity,
)
from smokejumper.contracts.fingerprint import event_fingerprint
from smokejumper.contracts.inbound import VerifiedInbound
from smokejumper.contracts.knowledge import KnowledgeBundle, KnowledgeItem
from smokejumper.contracts.ticketing import (
    TicketDraft,
    TicketProvider,
    TicketRef,
    TicketUpdate,
)
from smokejumper.contracts.tools import ToolCall, ToolResult, ToolTier

__all__ = [
    "AgentEvent",
    "ApprovalDecision",
    "ApprovalRequest",
    "Assignment",
    "AuditEvent",
    "AuditKind",
    "Budget",
    "Conclusion",
    "ConclusionStatus",
    "Contract",
    "DistillationCandidate",
    "Entity",
    "EventKind",
    "EventSource",
    "Finding",
    "KnowledgeBundle",
    "KnowledgeItem",
    "LlmCallPayload",
    "Severity",
    "Sha256Hex",
    "TicketDraft",
    "TicketProvider",
    "TicketRef",
    "TicketUpdate",
    "TokenUsage",
    "ToolCall",
    "ToolResult",
    "ToolTier",
    "VerifiedInbound",
    "event_fingerprint",
]
