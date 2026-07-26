"""TicketingPort — provider-neutral ticket lifecycle (SPEC 5.6, 5.10).

v1 ships the Linear adapter; GitHub Issues, Jira, and Asana are later adapters
behind this same interface, selected by `settings.ticketing.provider`.

The payload types come from `contracts/`, which SPEC 3 calls the source of truth.
Redefining them here as bare mappings would give the codebase two `TicketDraft`s
and leave the adapter conformance suite (SPEC 5.6) checking a type with no shape.
"""

from __future__ import annotations

from typing import Protocol

from smokejumper.contracts.ticketing import TicketDraft, TicketRef, TicketUpdate

__all__ = ["TicketDraft", "TicketRef", "TicketUpdate", "TicketingPort"]


class TicketingPort(Protocol):
    """Exactly one ticket per incident fingerprint, created once and then updated."""

    async def find_open_by_fingerprint(self, fingerprint: str) -> TicketRef | None:
        """The open ticket for this fingerprint, if any.

        This is what makes create-vs-update decidable without the caller keeping
        state, so a redelivered alert comments instead of filing a duplicate.
        """
        ...

    async def create(self, draft: TicketDraft) -> TicketRef: ...

    async def update(self, ref: TicketRef, update: TicketUpdate) -> None: ...

    async def close(self, ref: TicketRef, resolution: str) -> None: ...
