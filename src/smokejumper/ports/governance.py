"""GovernancePort — the host platform's policy identity (SPEC 5.10)."""

from __future__ import annotations

from typing import Protocol


class GovernancePort(Protocol):
    """Names the policy identity a run acts under, for the audit record.

    There is deliberately no `authorize()`: tier enforcement is authoritative in
    the tool executor (SPEC 5.5), and a second place that can say yes is a second
    place that can be wrong.
    """

    def identity(self) -> str:
        """The policy identity recorded as context on every B8 event."""
        ...
