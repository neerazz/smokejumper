"""MemoryPort — the bi-temporal episode store (SPEC 5.4, 5.10).

v1 knowledge is episodes plus recipes. Graph expansion is deferred, so there is
no `expand()`; recipes load from `recipes/*.yaml`, so they are not this port's
business either.

`Episode` stands in for a contract model that does not exist yet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

Episode = Mapping[str, Any]


class MemoryPort(Protocol):
    """Similarity search over past cases, and the write that adds one."""

    async def search_episodes(
        self,
        embedding: Sequence[float],
        *,
        limit: int,
        as_of: datetime | None = None,
    ) -> Sequence[Episode]:
        """Nearest episodes by vector similarity.

        `as_of` is the bi-temporal query: `None` means currently-valid facts,
        while a timestamp means "as believed at time T", which is what lets a
        replay reproduce the belief a decision was made on rather than today's.
        """
        ...

    async def write_episode(self, episode: Episode) -> None:
        """Record one closed case. Never overwrites: belief is appended, not edited."""
        ...
