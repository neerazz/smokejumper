"""B1 — `VerifiedInbound`, a transport payload that cleared the Auth port (SPEC §4)."""

from __future__ import annotations

import base64
from typing import Annotated

from pydantic import BeforeValidator, Field, PlainSerializer

from smokejumper.contracts.base import Contract
from smokejumper.contracts.events import EventSource


def _decode_body(value: object) -> object:
    if isinstance(value, str):
        return base64.b64decode(value, validate=True)
    return value


Base64Body = Annotated[
    bytes,
    BeforeValidator(_decode_body),
    PlainSerializer(
        lambda raw: base64.b64encode(raw).decode("ascii"),
        return_type=str,
        when_used="json",
    ),
]
"""Raw bytes in Python, base64 in JSON.

pydantic's own `Base64Bytes` reads its *input* as base64, which would force the
Receiver to pre-encode a body it holds raw. Signature verification is over the
exact bytes received, and a body need not be valid UTF-8, so the JSON form is
base64 rather than a decoded string.
"""


class VerifiedInbound(Contract):
    """The raw transport payload, after the Auth port validated its source.

    Verification happens before this model exists; holding a `VerifiedInbound`
    means the signature or shared secret already checked out (Slack Socket Mode
    authenticates with the app token and carries no HTTP signature at all).
    """

    source: EventSource
    headers: dict[str, str] = Field(default_factory=dict)
    body: Base64Body
