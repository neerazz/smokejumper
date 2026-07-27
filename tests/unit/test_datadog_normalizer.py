"""Datadog normalization and verification, driven by the committed real fixture.

The fixture is a resolved Datadog delivery, so these tests fail if the mapping
drifts from the payload an operator's template actually produces.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from smokejumper.contracts.events import EventKind, EventSource, Severity
from smokejumper.contracts.fingerprint import event_fingerprint
from smokejumper.receiver.normalizers import datadog
from smokejumper.receiver.verification import (
    DATADOG_TOKEN_HEADER,
    GENERIC_SIGNATURE_HEADER,
    PAGERDUTY_SIGNATURE_HEADER,
    verify_hmac_signature,
    verify_pagerduty_signature,
    verify_shared_token,
)

RECEIVED_AT = datetime(2026, 7, 26, 18, 30, tzinfo=UTC)


@pytest.fixture
def payload(repo_root: Path) -> dict[str, Any]:
    raw = (repo_root / "fixtures" / "webhooks" / "datadog.json").read_text(encoding="utf-8")
    return json.loads(raw)


def test_the_real_fixture_normalizes(payload: dict[str, Any]) -> None:
    event = datadog.normalize(payload, received_at=RECEIVED_AT)

    assert event.source is EventSource.DATADOG
    assert event.kind is EventKind.ALERT
    # The monitor ID, not the aggregation key.
    assert event.source_event_key == "142857301"
    assert event.severity is Severity.HIGH  # P2
    assert "online table lag" in event.title
    # $DATE is epoch milliseconds.
    assert event.occurred_at == datetime(2026, 7, 26, 18, 30, tzinfo=UTC)


def test_only_identity_tags_become_entities(payload: dict[str, Any]) -> None:
    """`team` and `monitor` are context, not identity, so they must not be entities.

    They are excluded because entities feed the fingerprint: a monitor renamed or
    re-owned would otherwise become a different incident.
    """
    event = datadog.normalize(payload, received_at=RECEIVED_AT)

    assert [(e.type, e.id) for e in event.entities] == [
        ("env", "prod"),
        ("region", "us-east-1"),
        ("service", "feature-store"),
        ("table", "merchant_features"),
    ]


def test_fingerprint_ignores_wording_and_tag_order(payload: dict[str, Any]) -> None:
    """A reworded alert with reshuffled tags is the same incident."""
    original = datadog.normalize(payload, received_at=RECEIVED_AT)

    reworded = dict(payload)
    reworded["title"] = "completely different wording"
    reworded["body"] = "and a different body"
    reworded["tags"] = "table:merchant_features,region:us-east-1,service:feature-store,env:prod"
    reworded["priority"] = "P4"
    reworded["date"] = "1784600000000"

    assert datadog.normalize(reworded, received_at=RECEIVED_AT).fingerprint == original.fingerprint


def test_fingerprint_changes_when_the_subject_changes(payload: dict[str, Any]) -> None:
    original = datadog.normalize(payload, received_at=RECEIVED_AT)

    other_table = dict(payload)
    other_table["tags"] = payload["tags"].replace("merchant_features", "advance_features")

    assert datadog.normalize(other_table, received_at=RECEIVED_AT).fingerprint != (
        original.fingerprint
    )


def test_fingerprint_is_the_canonical_hash(payload: dict[str, Any]) -> None:
    """Guards against the normalizer and the contract computing it differently."""
    event = datadog.normalize(payload, received_at=RECEIVED_AT)

    assert event.fingerprint == event_fingerprint(
        "datadog",
        "142857301",
        [
            ("env", "prod"),
            ("region", "us-east-1"),
            ("service", "feature-store"),
            ("table", "merchant_features"),
        ],
    )


def test_missing_alert_id_is_unparseable(payload: dict[str, Any]) -> None:
    """Without the monitor ID there is no stable identity to dedupe on."""
    del payload["alert_id"]

    with pytest.raises(datadog.UnparseablePayload, match="alert_id"):
        datadog.normalize(payload, received_at=RECEIVED_AT)


@pytest.mark.parametrize(
    ("priority", "alert_type", "expected"),
    [
        ("P1", "error", Severity.CRITICAL),
        ("P2", "error", Severity.HIGH),
        ("P3", "warning", Severity.MEDIUM),
        ("P4", "info", Severity.LOW),
        ("P5", "info", Severity.INFO),
        # No priority: fall back to alert_type, and never invent CRITICAL.
        ("", "error", Severity.HIGH),
        ("", "warning", Severity.MEDIUM),
        ("", "success", Severity.INFO),
        ("", "nonsense", Severity.INFO),
    ],
)
def test_severity_mapping(priority: str, alert_type: str, expected: Severity) -> None:
    assert datadog.severity_of({"priority": priority, "alert_type": alert_type}) is expected


def test_malformed_date_falls_back_to_arrival() -> None:
    """Losing a timestamp must not lose the alert."""
    assert datadog.occurred_at_of({"date": "not-a-number"}, received_at=RECEIVED_AT) == RECEIVED_AT
    assert datadog.occurred_at_of({}, received_at=RECEIVED_AT) == RECEIVED_AT


def test_recovery_is_detected(payload: dict[str, Any]) -> None:
    assert datadog.is_recovery(payload) is False
    assert datadog.is_recovery({**payload, "alert_transition": "Recovered"}) is True


# --- verification ----------------------------------------------------------


def test_shared_token_verification() -> None:
    secret = "s3cr3t-token"

    assert verify_shared_token({DATADOG_TOKEN_HEADER: secret}, secret=secret) is True
    # Case-insensitive header name, because senders disagree about casing.
    assert verify_shared_token({"x-smokejumper-token": secret}, secret=secret) is True
    assert verify_shared_token({DATADOG_TOKEN_HEADER: "wrong"}, secret=secret) is False
    assert verify_shared_token({}, secret=secret) is False


def test_an_unconfigured_secret_never_passes() -> None:
    """A forgotten secret must fail closed, not silently disable the check."""
    assert verify_shared_token({DATADOG_TOKEN_HEADER: ""}, secret="") is False
    assert verify_shared_token({DATADOG_TOKEN_HEADER: "anything"}, secret="") is False
    assert verify_hmac_signature(b"{}", {GENERIC_SIGNATURE_HEADER: "sha256=x"}, secret="") is False
    assert (
        verify_pagerduty_signature(b"{}", {PAGERDUTY_SIGNATURE_HEADER: "v1=x"}, secret="") is False
    )


def test_pagerduty_signature_accepts_any_valid_rotated_v1_digest() -> None:
    import hashlib
    import hmac as hmac_mod

    body = b'{"event":{"event_type":"incident.triggered"}}'
    secret = "pagerduty-webhook-secret"
    digest = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_pagerduty_signature(
        body,
        {PAGERDUTY_SIGNATURE_HEADER: f"v1={'0' * 64}, v1={digest}"},
        secret=secret,
    )
    assert not verify_pagerduty_signature(
        body,
        {PAGERDUTY_SIGNATURE_HEADER: f"v1={'0' * 64}"},
        secret=secret,
    )


def test_generic_hmac_is_computed_over_raw_bytes() -> None:
    import hashlib
    import hmac as hmac_mod

    secret = "shared"
    body = b'{"b":2,"a":1}'
    digest = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_hmac_signature(
        body, {GENERIC_SIGNATURE_HEADER: f"sha256={digest}"}, secret=secret
    )
    # Re-serializing would reorder keys and change the digest.
    assert not verify_hmac_signature(
        b'{"a":1,"b":2}', {GENERIC_SIGNATURE_HEADER: f"sha256={digest}"}, secret=secret
    )
    assert not verify_hmac_signature(body, {GENERIC_SIGNATURE_HEADER: digest}, secret=secret)
