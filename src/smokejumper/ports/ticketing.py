"""TicketingPort — provider-neutral ticket lifecycle (SPEC 5.6, 5.10).

v1 ships the Linear adapter; GitHub Issues, Jira, and Asana are later adapters
behind this same interface, selected by `settings.ticketing.provider`.

The mapping aliases stand in for the provider-neutral contract models that do not
exist yet; replacing them is a three-line edit once `contracts/` lands.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

TicketDraft = Mapping[str, Any]
TicketUpdate = Mapping[str, Any]
TicketRef = Mapping[str, Any]


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
