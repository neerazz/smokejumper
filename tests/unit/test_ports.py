"""Tests for the eight ports and their substitutes (SPEC 5.10).

Protocol conformance is checked by pyright, not at runtime: the annotated
assignments below fail the type gate if a substitute drifts from its port, which
catches the drift before it can reach a caller. None of the protocols is
`runtime_checkable`, because nothing needs `isinstance`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest

from smokejumper.config import STUB_SELECTIONS
from smokejumper.contracts.ticketing import TicketDraft, TicketUpdate
from smokejumper.ports import stubs
from smokejumper.ports.auth import AuthPort
from smokejumper.ports.channel import ChannelAdapter
from smokejumper.ports.governance import GovernancePort
from smokejumper.ports.memory import MemoryPort
from smokejumper.ports.model import ModelProvider
from smokejumper.ports.platform import PlatformPort
from smokejumper.ports.tenancy import SingleTenant, TenancyPort
from smokejumper.ports.ticketing import TicketingPort


def test_substitutes_satisfy_their_ports() -> None:
    """Static conformance for all eight ports; pyright is the assertion."""
    auth: AuthPort = stubs.AllowAll()
    governance: GovernancePort = stubs.NoopGovernance()
    tenancy: TenancyPort = SingleTenant()
    model: ModelProvider = stubs.RecordedModel([], embedding_dimension=4)
    platform: PlatformPort = stubs.FixturePlatform()
    channel: ChannelAdapter = stubs.FakeChannel()
    ticketing: TicketingPort = stubs.FixtureTicketing()
    memory: MemoryPort = stubs.InMemoryStore()

    assert [auth, governance, tenancy, model, platform, channel, ticketing, memory]


def test_every_substitute_announces_itself(caplog: pytest.LogCaptureFixture) -> None:
    """Every selected substitute logs its identity at boot, per SPEC 5.10."""
    with caplog.at_level(logging.WARNING, logger="smokejumper.ports.stubs"):
        stubs.AllowAll()
        stubs.NoopGovernance()
        stubs.RecordedModel([], embedding_dimension=4)
        stubs.FixturePlatform()
        stubs.FakeChannel()
        stubs.FixtureTicketing()
        stubs.InMemoryStore()

    messages = [record.getMessage() for record in caplog.records]
    announced = {name for name in STUB_SELECTIONS.values() if any(name in m for m in messages)}
    assert announced == set(STUB_SELECTIONS.values())


def test_stub_module_holds_exactly_the_configurable_substitutes() -> None:
    """The config Literals and this module must not drift apart."""
    exported = {
        name
        for name, value in vars(stubs).items()
        if isinstance(value, type) and value.__module__ == stubs.__name__
    }

    assert exported == set(STUB_SELECTIONS.values()) | {"FixtureTicket"}


def test_single_tenant_is_not_a_substitute() -> None:
    """Getting this backwards would make prod refuse the v1 tenancy contract."""
    assert SingleTenant.__module__ == "smokejumper.ports.tenancy"
    assert "SingleTenant" not in STUB_SELECTIONS.values()
    assert not hasattr(stubs, "SingleTenant")
    assert SingleTenant().tenant_id() == "default"


def test_model_port_imports_no_provider_sdk(src_root: Path) -> None:
    """The seam only holds if the SDK is not here yet either (SPEC 11.4)."""
    source = (src_root / "ports" / "model.py").read_text(encoding="utf-8")

    assert "import" in source  # guards against reading an empty file
    assert not any(
        line.startswith(("import ", "from "))
        and not line.startswith(("from __future__", "from collections.abc", "from typing"))
        for line in source.splitlines()
    )


async def test_recorded_model_replays_then_refuses() -> None:
    """A recorded run must not silently continue past the recording."""
    model = stubs.RecordedModel(["first"], embedding_dimension=3)

    assert await model.complete(role="worker", prompt="p", prompt_ref="agents/x@v1") == "first"
    with pytest.raises(LookupError, match="worker"):
        await model.complete(role="worker", prompt="p", prompt_ref="agents/x@v1")

    assert await model.embed(["a", "b"]) == [[0.0] * 3, [0.0] * 3]


async def test_fixture_ticketing_creates_once_then_updates() -> None:
    """The dry-run adapter exercises create-vs-update without an account (SPEC 5.6).

    Driven through the real `contracts/` models, not dicts — which is what makes
    this a conformance test the M2 Linear adapter can be held to as well.
    """
    ticketing = stubs.FixtureTicketing()
    fingerprint = "a" * 64
    run_id = uuid4()

    assert await ticketing.find_open_by_fingerprint(fingerprint) is None

    ref = await ticketing.create(
        TicketDraft(
            schema_version=1,
            fingerprint=fingerprint,
            run_id=run_id,
            title="disk full",
            body_md="root volume at 98%",
        )
    )
    assert await ticketing.find_open_by_fingerprint(fingerprint) == ref

    update = TicketUpdate(schema_version=1, run_id=run_id, comment_md="still firing")
    await ticketing.update(ref, update)
    assert ticketing.tickets[fingerprint].updates == [update]

    await ticketing.close(ref, "resolved")
    assert await ticketing.find_open_by_fingerprint(fingerprint) is None


async def test_in_memory_store_round_trips_episodes() -> None:
    memory = stubs.InMemoryStore()

    await memory.write_episode({"content": "first"})
    await memory.write_episode({"content": "second"})

    assert await memory.search_episodes([0.0], limit=1) == ({"content": "first"},)


async def test_fake_channel_records_sends_and_yields_nothing() -> None:
    channel = stubs.FakeChannel()

    message_ts = await channel.send(channel_id="C1", text="receipt", thread_ts="123.1")

    assert message_ts == "0.000000"
    assert channel.sent == [{"channel_id": "C1", "text": "receipt", "thread_ts": "123.1"}]
    assert [inbound async for inbound in channel.listen()] == []
