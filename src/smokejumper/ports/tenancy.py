"""TenancyPort and its v1 implementation (SPEC 5.10)."""

from __future__ import annotations

from typing import Final, Protocol


class TenancyPort(Protocol):
    """Names the tenant that owns a run, so stored rows can be attributed."""

    def tenant_id(self) -> str: ...


class SingleTenant:
    """The v1 implementation, not a stub.

    It lives here rather than in `stubs.py` because single tenancy IS the v1
    contract (SPEC 5.10) and `prod` allows it. Keeping it out of the stub module
    means the fail-closed gate cannot mistake it for one.
    """

    TENANT_ID: Final = "default"

    def tenant_id(self) -> str:
        return self.TENANT_ID
