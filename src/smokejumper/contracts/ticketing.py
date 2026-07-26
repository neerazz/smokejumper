"""Provider-neutral ticketing models for `TicketingPort` (SPEC §5.6).

Not a B-number: §5.6 names `TicketDraft`/`TicketUpdate`/`TicketRef` as contract
models so the port's signatures stay provider-neutral and every adapter can be
held to one conformance suite.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from smokejumper.contracts.base import Contract, Sha256Hex
from smokejumper.contracts.conclusions import ConclusionStatus


class TicketProvider(StrEnum):
    """v1 ships the Linear adapter; the rest are the named later adapters (§5.6)."""

    LINEAR = "linear"
    GITHUB = "github"
    JIRA = "jira"
    ASANA = "asana"


class TicketRef(Contract):
    """A ticket that exists, as the provider identifies it."""

    provider: TicketProvider
    external_id: str = Field(min_length=1)
    url: str | None = None


class TicketDraft(Contract):
    """A ticket to create.

    Carries `(fingerprint, run_id)` because that pair is the idempotency key: a
    redelivered webhook must update the open ticket, never post a second one.
    """

    fingerprint: Sha256Hex
    run_id: UUID
    title: str = Field(min_length=1)
    body_md: str


class TicketUpdate(Contract):
    """A comment, and optionally a new state, on an existing ticket.

    `status` is the B6 status rather than a provider workflow state; the adapter
    owns that mapping, so contracts stay free of provider vocabulary.
    """

    run_id: UUID
    comment_md: str
    status: ConclusionStatus | None = None
