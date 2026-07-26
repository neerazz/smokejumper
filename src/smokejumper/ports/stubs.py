"""The v1 port substitutes (SPEC 5.10).

Every class here announces itself when constructed, which is boot. The log line
is not the control, though: `prod` refuses to boot while any of these is selected
(SPEC 2d), because a stub that only writes a log line is indistinguishable from a
real port to everything except a human reading logs.

`SingleTenant` is deliberately not in this module — it is the v1 implementation,
not a substitute — and neither is any secret resolver, since `config.Settings` is
the only reader of the environment.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from smokejumper.contracts.ticketing import TicketProvider
from smokejumper.ports.channel import RawInbound
from smokejumper.ports.memory import Episode
from smokejumper.ports.model import ModelRole
from smokejumper.ports.platform import Asset, AssetQuery, Finding
from smokejumper.ports.ticketing import TicketDraft, TicketRef, TicketUpdate

logger = logging.getLogger(__name__)


def _announce(substitute: object, port: str) -> None:
    logger.warning(
        "port substitute in use: %s backs %s and enforces nothing",
        type(substitute).__name__,
        port,
    )


class AllowAll:
    """Verifies nothing and approves everything (AuthPort)."""

    def __init__(self) -> None:
        _announce(self, "AuthPort")

    def verify_inbound(self, *, source: str, headers: Mapping[str, str], body: bytes) -> bool:
        return True

    def mint_approval_token(self, *, binding: str) -> str:
        return secrets.token_urlsafe(32)

    def consume_approval_token(self, token: str, *, binding: str) -> bool:
        return True


class NoopGovernance:
    """Reports a fixed identity (GovernancePort)."""

    def __init__(self) -> None:
        _announce(self, "GovernancePort")

    def identity(self) -> str:
        return "noop"


class RecordedModel:
    """Replays queued completions instead of calling a provider (ModelProvider).

    This is what makes replay deterministic: the recorded response, not a live
    model, is the fixture (SPEC 5.8).
    """

    def __init__(self, completions: Sequence[str], *, embedding_dimension: int) -> None:
        _announce(self, "ModelProvider")
        self._completions = list(completions)
        self._embedding_dimension = embedding_dimension

    async def complete(self, *, role: ModelRole, prompt: str, prompt_ref: str) -> str:
        if not self._completions:
            raise LookupError(f"no recorded completion left for role {role!r}")
        return self._completions.pop(0)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * self._embedding_dimension for _ in texts]


class FixturePlatform:
    """Answers with no assets and keeps findings in memory (PlatformPort)."""

    def __init__(self, assets: Sequence[Asset] = ()) -> None:
        _announce(self, "PlatformPort")
        self.written: list[Finding] = []
        self._assets = list(assets)

    async def query_assets(self, query: AssetQuery) -> Sequence[Asset]:
        return tuple(self._assets)

    async def write_finding(self, finding: Finding) -> None:
        self.written.append(finding)


class FakeChannel:
    """Receives nothing and records what was sent (ChannelAdapter)."""

    def __init__(self) -> None:
        _announce(self, "ChannelAdapter")
        self.sent: list[RawInbound] = []

    async def listen(self) -> AsyncIterator[RawInbound]:
        return
        yield {}  # pragma: no cover - makes this an async generator

    async def send(self, *, channel_id: str, text: str, thread_ts: str | None = None) -> str:
        message_ts = f"{len(self.sent)}.000000"
        self.sent.append({"channel_id": channel_id, "text": text, "thread_ts": thread_ts})
        return message_ts


@dataclass
class FixtureTicket:
    """What the fixture tracker remembers about one ticket."""

    id: str
    closed: bool = False
    updates: list[TicketUpdate] = field(default_factory=list)


class FixtureTicketing:
    """An in-memory ticket tracker (TicketingPort).

    It is the dry-run adapter local development uses, and it implements the real
    fingerprint bookkeeping so create-vs-update is exercised without an account.

    It speaks the `contracts/` models rather than bare dicts, which is what lets
    pyright hold every adapter — this one and the real Linear adapter at M2 — to
    the same signatures.
    """

    def __init__(self) -> None:
        _announce(self, "TicketingPort")
        self.tickets: dict[str, FixtureTicket] = {}

    def _ref(self, ticket: FixtureTicket) -> TicketRef:
        return TicketRef(provider=TicketProvider.LINEAR, external_id=ticket.id)

    async def find_open_by_fingerprint(self, fingerprint: str) -> TicketRef | None:
        ticket = self.tickets.get(fingerprint)
        return None if ticket is None or ticket.closed else self._ref(ticket)

    async def create(self, draft: TicketDraft) -> TicketRef:
        ticket = FixtureTicket(id=f"FIXTURE-{len(self.tickets) + 1}")
        self.tickets[draft.fingerprint] = ticket
        return self._ref(ticket)

    async def update(self, ref: TicketRef, update: TicketUpdate) -> None:
        self._by_ref(ref).updates.append(update)

    async def close(self, ref: TicketRef, resolution: str) -> None:
        self._by_ref(ref).closed = True

    def _by_ref(self, ref: TicketRef) -> FixtureTicket:
        for ticket in self.tickets.values():
            if ticket.id == ref.external_id:
                return ticket
        raise KeyError(f"unknown ticket {ref.external_id!r}")


class InMemoryStore:
    """Holds episodes in a list (MemoryPort).

    There is no similarity ranking and no bi-temporal filtering: search returns
    insertion order. A test about retrieval quality must use Postgres, and
    pretending otherwise here would make that test lie.
    """

    def __init__(self) -> None:
        _announce(self, "MemoryPort")
        self.episodes: list[Episode] = []

    async def search_episodes(
        self,
        embedding: Sequence[float],
        *,
        limit: int,
        as_of: datetime | None = None,
    ) -> Sequence[Episode]:
        return tuple(self.episodes[:limit])

    async def write_episode(self, episode: Episode) -> None:
        self.episodes.append(episode)
