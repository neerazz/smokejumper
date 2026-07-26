"""PlatformPort — the external host platform, e.g. Curlix (B10, SPEC 5.10).

`skills.execute` from B10 is absent: no v1 caller executes a host skill, because
the privileged tier ships empty (SPEC 5.5). It belongs here when a caller exists.

The mapping aliases stand in for contract models that do not exist yet; replacing
them is a three-line edit once `contracts/` lands.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

AssetQuery = Mapping[str, Any]
Asset = Mapping[str, Any]
Finding = Mapping[str, Any]


class PlatformPort(Protocol):
    """Read host inventory, write findings back."""

    async def query_assets(self, query: AssetQuery) -> Sequence[Asset]:
        """Answer an inventory question, e.g. the deployment history `change.list` reads."""
        ...

    async def write_finding(self, finding: Finding) -> None:
        """Publish a finding to the host platform (SPEC 5.6)."""
        ...
