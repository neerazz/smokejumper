"""The one shared base for every boundary contract.

One base class, not a hierarchy: each of the B-contracts needs the same three
properties, and restating them sixteen times is how they drift apart.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""Lowercase hex SHA-256 digest, exactly as `hashlib.sha256().hexdigest()` emits it."""


class Contract(BaseModel):
    """Base for the boundary contracts of SPEC §4.

    `frozen` because a boundary payload is a recorded fact, not a workspace;
    mutating one after the recorder appended it would make the audit log a lie.
    `extra="forbid"` because a misspelled field that silently disappears is the
    exact failure these contracts exist to prevent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    """A `Literal` rather than an `int`: a replay that meets a version this build
    cannot interpret must fail loudly instead of guessing at the payload shape."""
