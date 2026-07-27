"""B1 — `VerifiedInbound`."""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from smokejumper.contracts import VerifiedInbound

RAW_BODY = b'{"alerts":[{"status":"firing"}]}\x00\xff'
ENCODED_BODY = base64.b64encode(RAW_BODY).decode("ascii")


def test_raw_bytes_survive_a_json_round_trip() -> None:
    """HMAC verification is over the exact bytes received, and a body is not
    guaranteed to be valid UTF-8, so the JSON form may neither lose nor replace one."""
    inbound = VerifiedInbound.model_validate(
        {
            "schema_version": 1,
            "source": "grafana",
            "headers": {"content-type": "application/json", "x-signature": "sha256=deadbeef"},
            "body": RAW_BODY,
        }
    )
    restored = VerifiedInbound.model_validate_json(inbound.model_dump_json())
    assert restored.body == RAW_BODY
    assert restored == inbound


def test_json_form_is_base64() -> None:
    inbound = VerifiedInbound.model_validate(
        {"schema_version": 1, "source": "generic", "body": RAW_BODY}
    )
    assert f'"body":"{ENCODED_BODY}"' in inbound.model_dump_json()


def test_a_string_body_is_read_as_base64() -> None:
    inbound = VerifiedInbound.model_validate(
        {"schema_version": 1, "source": "generic", "body": ENCODED_BODY}
    )
    assert inbound.body == RAW_BODY


def test_a_non_base64_string_body_is_rejected() -> None:
    with pytest.raises(ValidationError):
        VerifiedInbound.model_validate(
            {"schema_version": 1, "source": "generic", "body": "not base64 at all!"}
        )


def test_slack_needs_no_headers() -> None:
    inbound = VerifiedInbound.model_validate(
        {"schema_version": 1, "source": "slack", "body": b"{}"}
    )
    assert inbound.headers == {}


def test_source_enum_is_closed() -> None:
    with pytest.raises(ValidationError):
        VerifiedInbound.model_validate({"schema_version": 1, "source": "nagios", "body": b"{}"})
