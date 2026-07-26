"""B9 — `DistillationCandidate`, recorder → Distiller (SPEC §4)."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime

from smokejumper.contracts.base import Contract, Sha256Hex
from smokejumper.contracts.conclusions import Conclusion


class DistillationCandidate(Contract):
    """A closed case, offered to the Distiller.

    §4 describes B9 only as "a closed case bundle from the recorder → Distiller",
    so this carries exactly what that sentence names — which run, which incident,
    what it concluded, and when it closed — and nothing invented around it. The
    Distiller is post-v1; the boundary is defined now so the recorder does not
    have to grow a private shape later.
    """

    run_id: UUID
    fingerprint: Sha256Hex
    conclusion: Conclusion
    closed_at: AwareDatetime
