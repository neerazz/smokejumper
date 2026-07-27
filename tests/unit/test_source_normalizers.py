"""The four non-Datadog normalizers (SPEC 5.1).

Most of these tests are about *identity*, because that is where a normalizer bug
is expensive rather than merely wrong. `source_event_key` feeds the fingerprint,
which decides whether a delivery joins the open incident or opens a second
ticket, so each source gets a test pinning the field chosen and a test proving
the tempting wrong field would have failed.

The payloads are shaped like the real vendor bodies, not like the minimum the
code happens to read, so a mapping that only works against a stub fails here.
The last section drives the committed golden payloads in `fixtures/webhooks/`
(SPEC §8) so the fixtures cannot rot away from the code that reads them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from typing import Any

import pytest

from smokejumper.contracts.events import EventKind, EventSource, Severity
from smokejumper.contracts.fingerprint import event_fingerprint
from smokejumper.receiver.normalizers.datadog import UnparseablePayload
from smokejumper.receiver.normalizers.sources import (
    normalize_alertmanager,
    normalize_generic,
    normalize_grafana,
    normalize_pagerduty,
    resolved_alertmanager,
    resolved_grafana,
    resolved_pagerduty,
)
from smokejumper.receiver.verification import verify_source_ip

RECEIVED_AT = datetime(2026, 7, 26, 18, 30, tzinfo=UTC)


# --- PagerDuty -------------------------------------------------------------


def pagerduty_payload(**overrides: Any) -> dict[str, Any]:
    """A PagerDuty v3 `incident.triggered` delivery."""
    data: dict[str, Any] = {
        "id": "PGR0VU2",
        "type": "incident",
        "self": "https://api.pagerduty.com/incidents/PGR0VU2",
        "html_url": "https://acme.pagerduty.com/incidents/PGR0VU2",
        "number": 1701,
        "status": "triggered",
        "incident_key": "feature-store/online-table-lag",
        "created_at": "2026-07-26T18:29:41Z",
        "title": "online table lag above 15m",
        "service": {
            "id": "PF9KMXH",
            "summary": "feature-store",
            "type": "service_reference",
        },
        "priority": {"id": "P53ZZH5", "summary": "P2", "type": "priority_reference"},
        "urgency": "high",
        "body": {"type": "incident_body", "details": "lag is 22 minutes and climbing"},
    }
    data.update(overrides)
    return {
        "event": {
            "id": "01F2VH8N4C",
            "event_type": "incident.triggered",
            "resource_type": "incident",
            "occurred_at": "2026-07-26T18:29:41Z",
            "data": data,
        }
    }


def test_pagerduty_maps_the_real_v3_shape() -> None:
    (event,) = normalize_pagerduty(pagerduty_payload(), received_at=RECEIVED_AT)

    assert event.source is EventSource.PAGERDUTY
    assert event.kind is EventKind.ALERT
    assert event.source_event_key == "feature-store/online-table-lag"
    assert event.severity is Severity.HIGH  # P2
    assert event.title == "online table lag above 15m"
    assert event.body == "lag is 22 minutes and climbing"
    assert [(e.type, e.id) for e in event.entities] == [("service", "feature-store")]
    assert event.occurred_at == datetime(2026, 7, 26, 18, 29, 41, tzinfo=UTC)


def test_pagerduty_identity_survives_a_new_incident_object() -> None:
    """The dedupe key is the identity; `id` is not.

    PagerDuty mints a new incident `id` when the same condition re-triggers after
    a resolve, so keying on `id` would make every re-trigger a new incident and
    quietly defeat the dedupe window.
    """
    first = normalize_pagerduty(pagerduty_payload(), received_at=RECEIVED_AT)[0]
    second = normalize_pagerduty(
        pagerduty_payload(id="PDIFFERENT", number=1702), received_at=RECEIVED_AT
    )[0]

    assert first.fingerprint == second.fingerprint


def test_pagerduty_falls_back_through_the_key_fields() -> None:
    """Events API v2 says `dedup_key`, v3 incidents say `incident_key`."""
    v2 = pagerduty_payload(dedup_key="events-api-key")
    assert normalize_pagerduty(v2, received_at=RECEIVED_AT)[0].source_event_key == "events-api-key"

    keyless = pagerduty_payload()
    del keyless["event"]["data"]["incident_key"]
    with pytest.raises(UnparseablePayload, match=r"incident\.id is reminted"):
        normalize_pagerduty(keyless, received_at=RECEIVED_AT)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"priority": {"summary": "P1"}}, Severity.CRITICAL),
        ({"priority": {"summary": "P5"}}, Severity.INFO),
        # Events API v2 alerts carry `severity` and no priority.
        ({"priority": None, "severity": "critical"}, Severity.CRITICAL),
        ({"priority": None, "severity": "warning"}, Severity.MEDIUM),
        # Neither: urgency is the only field always present.
        ({"priority": None, "urgency": "low"}, Severity.LOW),
        ({"priority": None, "urgency": "high"}, Severity.HIGH),
    ],
)
def test_pagerduty_severity_prefers_the_most_specific_signal(
    data: dict[str, Any], expected: Severity
) -> None:
    payload = pagerduty_payload(**data)

    assert normalize_pagerduty(payload, received_at=RECEIVED_AT)[0].severity is expected


def test_pagerduty_tolerates_null_sub_objects() -> None:
    """PagerDuty sends `null` for sub-objects the incident does not have.

    A normalizer that assumed a dict would raise `AttributeError`, which is not a
    `ValueError`, so the route would 500 instead of quarantining.
    """
    payload = pagerduty_payload(service=None, body=None, priority=None)

    (event,) = normalize_pagerduty(payload, received_at=RECEIVED_AT)

    assert event.entities == []
    assert event.body == ""


def test_pagerduty_without_an_incident_is_unparseable() -> None:
    with pytest.raises(UnparseablePayload, match=r"event\.data"):
        normalize_pagerduty({"event": {"event_type": "ping"}}, received_at=RECEIVED_AT)


def test_pagerduty_without_any_key_is_unparseable() -> None:
    payload = pagerduty_payload()
    del payload["event"]["data"]["incident_key"]

    with pytest.raises(UnparseablePayload, match="dedup_key"):
        normalize_pagerduty(payload, received_at=RECEIVED_AT)


def test_pagerduty_resolution_is_not_an_alert_and_preserves_incident_identity() -> None:
    triggered = pagerduty_payload()
    resolved = pagerduty_payload()
    resolved["event"]["event_type"] = "incident.resolved"

    (firing,) = normalize_pagerduty(triggered, received_at=RECEIVED_AT)

    assert normalize_pagerduty(resolved, received_at=RECEIVED_AT) == []
    assert (
        resolved_pagerduty(resolved, received_at=RECEIVED_AT)[0].fingerprint == firing.fingerprint
    )


# --- Grafana / Alertmanager ------------------------------------------------


def alert(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "firing",
        "fingerprint": "3f2a91c0deadbeef",
        "startsAt": "2026-07-26T18:25:03Z",
        "labels": {
            "alertname": "OnlineTableLag",
            "severity": "critical",
            "service": "feature-store",
            "env": "prod",
            "table": "merchant_features",
            "team": "data-platform",
            "__alert_rule_uid__": "adm7x2k",
        },
        "annotations": {
            "summary": "online table lag above 15m",
            "description": "merchant_features lag is 22 minutes",
        },
    }
    payload.update(overrides)
    return payload


def batch(*alerts: dict[str, Any]) -> dict[str, Any]:
    return {"receiver": "smokejumper", "status": "firing", "alerts": list(alerts)}


@pytest.mark.parametrize(
    ("normalize", "source"),
    [
        (normalize_grafana, EventSource.GRAFANA),
        (normalize_alertmanager, EventSource.ALERTMANAGER),
    ],
)
def test_label_sources_map_one_alert(normalize: Any, source: EventSource) -> None:
    (event,) = normalize(batch(alert()), received_at=RECEIVED_AT)

    assert event.source is source
    assert event.source_event_key == "3f2a91c0deadbeef"
    assert event.severity is Severity.CRITICAL
    assert event.title == "OnlineTableLag"
    assert event.body == "merchant_features lag is 22 minutes"
    assert event.occurred_at == datetime(2026, 7, 26, 18, 25, 3, tzinfo=UTC)
    # The individual alert is stored, not the whole batch: the batch is a
    # transport detail and the other alerts in it belong to other incidents.
    assert event.raw["fingerprint"] == "3f2a91c0deadbeef"


def test_each_alert_in_a_batch_is_its_own_incident() -> None:
    """One POST, several unrelated failures. Collapsing them loses tickets."""
    other = alert(
        fingerprint="99887766aabbccdd",
        labels={**alert()["labels"], "table": "advance_features"},
    )

    events = normalize_grafana(batch(alert(), other), received_at=RECEIVED_AT)

    assert len(events) == 2
    assert len({event.fingerprint for event in events}) == 2


def test_multi_dimensional_rule_instances_do_not_collapse() -> None:
    """`alertname` is shared by every instance of one rule, so it is not identity.

    A rule that fires per table sends the same `alertname` for each. Keying on it
    would file one ticket for the first table and silently swallow the rest.
    """
    events = normalize_grafana(
        batch(
            alert(fingerprint="aaa1", labels={**alert()["labels"], "table": "t1"}),
            alert(fingerprint="bbb2", labels={**alert()["labels"], "table": "t2"}),
        ),
        received_at=RECEIVED_AT,
    )

    assert {event.title for event in events} == {"OnlineTableLag"}
    assert len({event.fingerprint for event in events}) == 2


def test_alert_identity_falls_back_to_the_rule_uid() -> None:
    """Grafana below 9.x omits `fingerprint`, but always sends the rule UID."""
    without = alert()
    del without["fingerprint"]

    (event,) = normalize_grafana(batch(without), received_at=RECEIVED_AT)

    assert event.source_event_key == "adm7x2k"


def test_only_identity_labels_become_entities() -> None:
    """`team` and `alertname` are context. Entities feed the fingerprint."""
    (event,) = normalize_alertmanager(batch(alert()), received_at=RECEIVED_AT)

    assert [(e.type, e.id) for e in event.entities] == [
        ("env", "prod"),
        ("service", "feature-store"),
        ("table", "merchant_features"),
    ]


def test_reassigning_the_team_does_not_change_the_incident() -> None:
    original = normalize_alertmanager(batch(alert()), received_at=RECEIVED_AT)[0]
    reassigned = normalize_alertmanager(
        batch(alert(labels={**alert()["labels"], "team": "sre"})), received_at=RECEIVED_AT
    )[0]

    assert original.fingerprint == reassigned.fingerprint


def test_resolved_alerts_are_dropped() -> None:
    """A resolution ends an incident. Enqueuing it would investigate a non-event."""
    events = normalize_grafana(
        batch(alert(status="resolved"), alert(fingerprint="still-firing")),
        received_at=RECEIVED_AT,
    )

    assert [event.source_event_key for event in events] == ["still-firing"]


def test_an_all_resolved_batch_yields_nothing() -> None:
    assert normalize_grafana(batch(alert(status="resolved")), received_at=RECEIVED_AT) == []


def test_resolved_label_alerts_preserve_the_firing_identity() -> None:
    firing = alert(fingerprint="same-incident")
    resolved = alert(fingerprint="same-incident", status="resolved")

    grafana_firing = normalize_grafana(batch(firing), received_at=RECEIVED_AT)[0]
    alertmanager_firing = normalize_alertmanager(batch(firing), received_at=RECEIVED_AT)[0]

    assert resolved_grafana(batch(resolved), received_at=RECEIVED_AT)[0].fingerprint == (
        grafana_firing.fingerprint
    )
    assert resolved_alertmanager(batch(resolved), received_at=RECEIVED_AT)[0].fingerprint == (
        alertmanager_firing.fingerprint
    )


def test_an_empty_batch_is_unparseable() -> None:
    """Distinct from an all-resolved batch: this one is malformed, not benign."""
    with pytest.raises(UnparseablePayload, match="alerts"):
        normalize_alertmanager({"alerts": []}, received_at=RECEIVED_AT)

    with pytest.raises(UnparseablePayload, match="alerts"):
        normalize_alertmanager({"status": "firing"}, received_at=RECEIVED_AT)


def test_an_alert_with_no_identity_is_unparseable() -> None:
    anonymous = alert()
    del anonymous["fingerprint"]
    del anonymous["labels"]["__alert_rule_uid__"]

    with pytest.raises(UnparseablePayload, match="fingerprint"):
        normalize_grafana(batch(anonymous), received_at=RECEIVED_AT)


def test_label_sources_tolerate_missing_label_objects() -> None:
    bare = {"status": "firing", "fingerprint": "bare1", "labels": None, "annotations": None}

    (event,) = normalize_grafana(batch(bare), received_at=RECEIVED_AT)

    assert event.entities == []
    assert event.severity is Severity.MEDIUM
    assert event.title == "grafana alert bare1"


# --- generic ---------------------------------------------------------------


def test_generic_maps_the_documented_contract() -> None:
    payload = {
        "event_id": "deploy-4711-canary-failed",
        "severity": "critical",
        "title": "canary failed",
        "body": "error rate 12% over 5m",
        "occurred_at": "2026-07-26T18:20:00Z",
        "entities": [
            {"type": "service", "id": "checkout"},
            {"type": "env", "id": "prod"},
        ],
    }

    (event,) = normalize_generic(payload, received_at=RECEIVED_AT)

    assert event.source is EventSource.GENERIC
    assert event.source_event_key == "deploy-4711-canary-failed"
    assert event.severity is Severity.CRITICAL
    assert [(e.type, e.id) for e in event.entities] == [("env", "prod"), ("service", "checkout")]
    assert event.occurred_at == datetime(2026, 7, 26, 18, 20, tzinfo=UTC)


def test_generic_entities_are_sorted_and_deduplicated() -> None:
    """Two callers sending the same entities in a different order agree."""
    forwards = normalize_generic(
        {"event_id": "e1", "entities": [{"type": "b", "id": "2"}, {"type": "a", "id": "1"}]},
        received_at=RECEIVED_AT,
    )[0]
    a, b = {"type": "a", "id": "1"}, {"type": "b", "id": "2"}
    backwards = normalize_generic(
        {"event_id": "e1", "entities": [a, b, a]},
        received_at=RECEIVED_AT,
    )[0]

    assert forwards.fingerprint == backwards.fingerprint
    assert len(backwards.entities) == 2


def test_generic_requires_a_stable_id() -> None:
    """Our own contract, so it can be strict where the vendors cannot be."""
    with pytest.raises(UnparseablePayload, match="event_id"):
        normalize_generic({"title": "something broke"}, received_at=RECEIVED_AT)


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        ("critical", Severity.CRITICAL),
        ("info", Severity.INFO),
        # Synonyms callers actually send.
        ("error", Severity.HIGH),
        ("warn", Severity.MEDIUM),
        # Unrecognized never escalates to CRITICAL.
        ("catastrophic", Severity.MEDIUM),
        ("", Severity.MEDIUM),
    ],
)
def test_generic_severity_never_invents_an_escalation(severity: str, expected: Severity) -> None:
    (event,) = normalize_generic({"event_id": "e", "severity": severity}, received_at=RECEIVED_AT)

    assert event.severity is expected


# --- shared behaviour ------------------------------------------------------


@pytest.mark.parametrize(
    "occurred_at",
    ["not-a-timestamp", "", "2026-13-45T99:99:99Z"],
)
def test_a_bad_timestamp_never_loses_the_alert(occurred_at: str) -> None:
    (event,) = normalize_generic(
        {"event_id": "e", "occurred_at": occurred_at}, received_at=RECEIVED_AT
    )

    assert event.occurred_at == RECEIVED_AT


def test_a_naive_timestamp_is_read_as_utc() -> None:
    (event,) = normalize_generic(
        {"event_id": "e", "occurred_at": "2026-07-26T18:20:00"}, received_at=RECEIVED_AT
    )

    assert event.occurred_at == datetime(2026, 7, 26, 18, 20, tzinfo=UTC)


def test_the_same_key_from_two_sources_is_two_incidents() -> None:
    """The source is part of the fingerprint, so keyspaces cannot collide."""
    generic = normalize_generic({"event_id": "shared-key"}, received_at=RECEIVED_AT)[0]
    grafana = normalize_grafana(
        batch({"status": "firing", "fingerprint": "shared-key"}), received_at=RECEIVED_AT
    )[0]

    assert generic.fingerprint != grafana.fingerprint


def test_fingerprints_match_the_canonical_hash() -> None:
    """Guards against a normalizer computing identity differently to the contract."""
    (event,) = normalize_alertmanager(batch(alert()), received_at=RECEIVED_AT)

    assert event.fingerprint == event_fingerprint(
        "alertmanager",
        "3f2a91c0deadbeef",
        [("env", "prod"), ("service", "feature-store"), ("table", "merchant_features")],
    )


@pytest.mark.parametrize(
    "normalize",
    [normalize_pagerduty, normalize_grafana, normalize_alertmanager, normalize_generic],
)
def test_a_non_object_body_is_unparseable_everywhere(normalize: Any) -> None:
    """`UnparseablePayload` is a `ValueError`, which the route turns into a
    quarantine row rather than a 500."""
    with pytest.raises(UnparseablePayload):
        normalize(["not", "an", "object"], received_at=RECEIVED_AT)


# --- Alertmanager network verification -------------------------------------

LAB = [IPv4Network("10.4.0.0/16"), IPv6Network("fd00::/8")]


@pytest.mark.parametrize(
    ("peer", "allowed"),
    [
        ("10.4.7.9", True),
        ("fd00::1", True),
        ("10.5.7.9", False),
        ("203.0.113.7", False),
        # No peer address at all, e.g. a closed transport.
        (None, False),
        # Not an address. A hostname here means something upstream rewrote it.
        ("alertmanager.internal", False),
    ],
)
def test_alertmanager_peer_must_be_in_the_allowlist(peer: str | None, allowed: bool) -> None:
    assert verify_source_ip(peer, allowlist=LAB) is allowed


def test_an_unconfigured_allowlist_admits_nothing() -> None:
    """Alertmanager sends no credential, so a forgotten allowlist would otherwise
    turn this endpoint into an open, unauthenticated write path."""
    assert verify_source_ip("10.4.7.9", allowlist=[]) is False


# --- committed golden payloads ---------------------------------------------


def _golden(repo_root: Path, name: str) -> dict[str, Any]:
    raw = (repo_root / "fixtures" / "webhooks" / f"{name}.json").read_text(encoding="utf-8")
    return json.loads(raw)


def test_the_pagerduty_golden_payload_normalizes(repo_root: Path) -> None:
    (event,) = normalize_pagerduty(_golden(repo_root, "pagerduty"), received_at=RECEIVED_AT)

    assert event.source_event_key == "feature-store/online-table-lag"
    assert event.severity is Severity.HIGH
    assert [(e.type, e.id) for e in event.entities] == [("service", "feature-store")]


def test_the_grafana_golden_payload_normalizes(repo_root: Path) -> None:
    """The fixture carries two firing alerts and one resolved, which is the
    batch shape a single-event reader gets wrong."""
    events = normalize_grafana(_golden(repo_root, "grafana"), received_at=RECEIVED_AT)

    assert [event.source_event_key for event in events] == [
        "3f2a91c0deadbeef",
        "9b17c4de01234567",
    ]
    assert [event.severity for event in events] == [Severity.CRITICAL, Severity.MEDIUM]
    # `grafana_folder` and `team` are context, so they stay out of identity.
    assert [(e.type, e.id) for e in events[0].entities] == [
        ("env", "prod"),
        ("service", "feature-store"),
        ("table", "merchant_features"),
    ]


def test_the_alertmanager_golden_payload_normalizes(repo_root: Path) -> None:
    (event,) = normalize_alertmanager(_golden(repo_root, "alertmanager"), received_at=RECEIVED_AT)

    assert event.source_event_key == "7d3b1e5a90c2f481"
    assert event.severity is Severity.CRITICAL
    # `instance` and `job` are scrape details, not the subject of the incident.
    assert [(e.type, e.id) for e in event.entities] == [
        ("env", "prod"),
        ("kube_namespace", "payments"),
        ("service", "checkout"),
    ]
    assert event.occurred_at == datetime(2026, 7, 26, 18, 25, 3, 884000, tzinfo=UTC)


def test_the_generic_golden_payload_normalizes(repo_root: Path) -> None:
    (event,) = normalize_generic(_golden(repo_root, "generic"), received_at=RECEIVED_AT)

    assert event.source_event_key == "deploy-4711-canary-failed"
    assert event.severity is Severity.CRITICAL
    assert [(e.type, e.id) for e in event.entities] == [
        ("env", "prod"),
        ("kube_namespace", "payments"),
        ("service", "checkout"),
    ]


@pytest.mark.parametrize("source", ["datadog", "pagerduty", "grafana", "alertmanager", "generic"])
def test_every_http_source_has_a_golden_payload(repo_root: Path, source: str) -> None:
    """SPEC §8 requires one per source; this is what notices when the next one lands
    without a fixture."""
    assert (repo_root / "fixtures" / "webhooks" / f"{source}.json").is_file()
