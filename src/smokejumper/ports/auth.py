"""AuthPort — transport verification and approval-token custody (SPEC 5.10).

Argument types are primitives rather than the B1/B5 contract models only because
`contracts/` does not exist yet; SPEC 3 permits ports to import contracts, so
these signatures should be tightened once it lands.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class AuthPort(Protocol):
    """Decides whether an inbound transport is trustworthy, and mints B5 tokens."""

    def verify_inbound(self, *, source: str, headers: Mapping[str, str], body: bytes) -> bool:
        """Verify a webhook signature or shared secret over the raw body (B1).

        The body is bytes because HMAC is computed over exactly what arrived; a
        re-serialized payload verifies against a different digest.
        """
        ...

    def mint_approval_token(self, *, binding: str) -> str:
        """Mint one single-use approval token bound to `binding` (B5).

        `binding` is the digest over `(channel_id, thread_ts, tool_call_sha256)`,
        so a token approved for one tool call cannot authorize another.
        """
        ...

    def consume_approval_token(self, token: str, *, binding: str) -> bool:
        """Spend a token, returning whether it was valid, unexpired, and unused.

        Consumption must be atomic: two Slack button clicks race, and only one
        may win.
        """
        ...
