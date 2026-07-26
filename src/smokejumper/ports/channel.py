"""ChannelAdapter — inbound chat and outbound receipts (SPEC 5.1, 5.10).

v1 ships exactly one adapter, Slack. Telegram and email are designed for behind
this port and deliberately not built.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol

RawInbound = Mapping[str, Any]


class ChannelAdapter(Protocol):
    """Two methods, because a channel only ever listens and replies."""

    def listen(self) -> AsyncIterator[RawInbound]:
        """Yield raw inbound payloads until cancelled.

        Raw, not normalized: verification and normalization belong to the
        Receiver, so an adapter cannot decide what counts as a valid event.
        """
        ...

    async def send(self, *, channel_id: str, text: str, thread_ts: str | None = None) -> str:
        """Post a message and return its timestamp.

        The timestamp is the return value because a receipt threads under the
        alerting message and an ApprovalRequest is bound to it (B5).
        """
        ...
