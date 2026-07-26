"""The four non-Datadog normalizers (SPEC 5.1).

Each vendor names the same three things differently, and getting the *identity*
mapping wrong is the expensive mistake: `source_event_key` feeds the fingerprint,
so a key that changes between deliveries of one incident opens a second ticket.
Per source, the identity is:

- **PagerDuty** `dedup_key` \u2014 PagerDuty's own deduplication key, which is exactly
  this concept. Not `incident.id`, which differs per incident object.
- **Grafana** `fingerprint` when present (Grafana 9+ unified alerting computes a
  stable one per alert instance), falling back to the rule UID. Not `alertname`,
  which is shared by every instance of a multi-dimensional rule.
- **Alertmanager** `fingerprint` per alert, same reasoning.
- **Generic** the caller's `event_id`, which the contract requires them to make
  stable.

Grafana and Alertmanager both post *batches*. Each alert in the batch is its own
incident with its own fingerprint, so they return a list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from smokejumper.contracts.events import (
    AgentEvent,
    Entity,
    EventKind,
    EventSource,
    Severity,
)
from smokejumper.contracts.fingerprint import event_fingerprint
from smokejumper.receiver.normalizers.datadog import (
    IDENTITY_TAG_KEYS,
    UnparseablePayload,
)

# Label keys that identify a subject, shared across the label-based sources.
# Same allowlist rule as Datadog: entities feed the fingerprint, so a volatile
# label would re-identify an incident mid-flight.
_LABEL_SEVERITY = {
    "critical": Severity.CRITICAL,
    "error": Severity.HIGH,
    "high": Severity.HIGH,
    "page": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "warn": Severity.MEDIUM,
    "minor": Severity.LOW,
    "low": Severity.LOW,
    "info": Severity.INFO,
    "none": Severity.INFO,
}

# PagerDuty carries three different severity signals depending on which product
# sent the webhook, so all three are mapped and tried in order of specificity.
# `priority` is an explicit operator judgement; `severity` only appears on Events
# API v2 alerts; `urgency` is always present but only says paging/not-paging.
_PD_PRIORITY = {
    "P1": Severity.CRITICAL,
    "P2": Severity.HIGH,
    "P3": Severity.MEDIUM,
    "P4": Severity.LOW,
    "P5": Severity.INFO,
}

_PD_SEVERITY = {
    "critical": Severity.CRITICAL,
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "info": Severity.INFO,
}

_PD_URGENCY = {
    "high": Severity.HIGH,
    "low": Severity.LOW,
}


def _text(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    return "" if value is None else str(value).strip()


def _obj(source: dict[str, Any], key: str) -> dict[str, Any]:
    """A nested object, or an empty one.

    Vendor payloads omit optional sub-objects and occasionally send `null` where
    the docs promise a dict, so every nested read goes through here instead of
    guarding at each call site.
    """
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def _pagerduty_severity(data: dict[str, Any]) -> Severity:
    """Priority first, then Events-API severity, then urgency.

    Ordered by how much the field actually knows. A v3 incident webhook has no
    `severity` at all, so reading only that field would classify every incident
    — including a P5 — at the default, and severity feeds the storm brake.
    """
    priority = _text(_obj(data, "priority"), "summary").upper()
    if priority in _PD_PRIORITY:
        return _PD_PRIORITY[priority]

    severity = _text(data, "severity").lower()
    if severity in _PD_SEVERITY:
        return _PD_SEVERITY[severity]

    # Urgency is the only field guaranteed present, and it distinguishes exactly
    # one thing: whether PagerDuty woke somebody up.
    return _PD_URGENCY.get(_text(data, "urgency").lower(), Severity.HIGH)


def _entities_from_labels(labels: dict[str, Any]) -> list[Entity]:
    """Identity-bearing labels only, sorted and deduplicated."""
    found: set[tuple[str, str]] = set()
    for key, value in labels.items():
        name = str(key).strip().lower()
        text = str(value).strip()
        if name in IDENTITY_TAG_KEYS and text:
            found.add((name, text))
    return [Entity(type=k, id=v) for k, v in sorted(found)]


def _build(
    *,
    source: EventSource,
    key: str,
    severity: Severity,
    title: str,
    body: str,
    entities: list[Entity],
    occurred_at: datetime,
    received_at: datetime,
    raw: dict[str, Any],
) -> AgentEvent:
    return AgentEvent(
        id=uuid4(),
        source=source,
        kind=EventKind.ALERT,
        source_event_key=key,
        fingerprint=event_fingerprint(source.value, key, [(e.type, e.id) for e in entities]),
        severity=severity,
        title=title or f"{source.value} alert {key}",
        body=body,
        entities=entities,
        occurred_at=occurred_at,
        received_at=received_at,
        raw=raw,
    )


def _parse_iso(value: str, *, fallback: datetime) -> datetime:
    """Vendor timestamps are ISO-8601, often with `Z`. Never fail the alert on one."""
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def normalize_pagerduty(payload: dict[str, Any], *, received_at: datetime) -> list[AgentEvent]:
    """PagerDuty v3 webhook. `event.data` holds the incident."""
    if not isinstance(payload, dict):
        raise UnparseablePayload("body is not a JSON object")

    data = _obj(_obj(payload, "event"), "data") or _obj(payload, "incident")
    if not data:
        raise UnparseablePayload("event.data (or incident) is required")

    # dedup_key is PagerDuty's own idea of "same incident", which is precisely
    # what the fingerprint needs. incident.id changes per incident object.
    key = _text(data, "dedup_key") or _text(data, "incident_key") or _text(data, "id")
    if not key:
        raise UnparseablePayload("dedup_key (or id) is required: it is the incident identity")

    body_obj = _obj(data, "body")
    service_name = _text(_obj(data, "service"), "summary")
    entities = [Entity(type="service", id=service_name)] if service_name else []

    return [
        _build(
            source=EventSource.PAGERDUTY,
            key=key,
            severity=_pagerduty_severity(data),
            title=_text(data, "title") or _text(data, "summary"),
            body=_text(body_obj, "details"),
            entities=entities,
            occurred_at=_parse_iso(_text(data, "created_at"), fallback=received_at),
            received_at=received_at,
            raw=payload,
        )
    ]


def _label_batch(
    payload: dict[str, Any],
    *,
    source: EventSource,
    received_at: datetime,
) -> list[AgentEvent]:
    """Shared shape for Grafana unified alerting and Alertmanager.

    Both post `{"alerts": [{labels, annotations, status, fingerprint, startsAt}]}`.
    Resolved alerts are dropped rather than enqueued: they end an incident, and a
    Receiver that enqueued them would start an investigation into something that
    just stopped happening.
    """
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        raise UnparseablePayload("alerts[] is required and must be non-empty")

    events: list[AgentEvent] = []
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        if _text(alert, "status").lower() == "resolved":
            continue

        labels = _obj(alert, "labels")
        annotations = _obj(alert, "annotations")

        key = _text(alert, "fingerprint") or _text(labels, "__alert_rule_uid__")
        if not key:
            raise UnparseablePayload(
                "fingerprint (or __alert_rule_uid__) is required: it is the alert identity"
            )

        events.append(
            _build(
                source=source,
                key=key,
                severity=_LABEL_SEVERITY.get(_text(labels, "severity").lower(), Severity.MEDIUM),
                title=_text(labels, "alertname") or _text(annotations, "summary"),
                body=_text(annotations, "description") or _text(annotations, "summary"),
                entities=_entities_from_labels(labels),
                occurred_at=_parse_iso(_text(alert, "startsAt"), fallback=received_at),
                received_at=received_at,
                raw=alert,
            )
        )
    return events


def normalize_grafana(payload: dict[str, Any], *, received_at: datetime) -> list[AgentEvent]:
    """Grafana 9+ unified alerting, which posts the Alertmanager shape."""
    if not isinstance(payload, dict):
        raise UnparseablePayload("body is not a JSON object")
    return _label_batch(payload, source=EventSource.GRAFANA, received_at=received_at)


def normalize_alertmanager(payload: dict[str, Any], *, received_at: datetime) -> list[AgentEvent]:
    """Prometheus Alertmanager webhook."""
    if not isinstance(payload, dict):
        raise UnparseablePayload("body is not a JSON object")
    return _label_batch(payload, source=EventSource.ALERTMANAGER, received_at=received_at)


def normalize_generic(payload: dict[str, Any], *, received_at: datetime) -> list[AgentEvent]:
    """Our own contract, so it is the strictest: the caller owns a stable id."""
    if not isinstance(payload, dict):
        raise UnparseablePayload("body is not a JSON object")

    key = _text(payload, "event_id")
    if not key:
        raise UnparseablePayload("event_id is required and must be stable per incident")

    raw_entities = payload.get("entities")
    entities: list[Entity] = []
    if isinstance(raw_entities, list):
        seen: set[tuple[str, str]] = set()
        for item in raw_entities:
            if isinstance(item, dict) and item.get("type") and item.get("id"):
                seen.add((str(item["type"]).strip(), str(item["id"]).strip()))
        entities = [Entity(type=t, id=i) for t, i in sorted(seen)]

    severity_text = _text(payload, "severity").lower()
    try:
        severity = Severity(severity_text)
    except ValueError:
        severity = _LABEL_SEVERITY.get(severity_text, Severity.MEDIUM)

    return [
        _build(
            source=EventSource.GENERIC,
            key=key,
            severity=severity,
            title=_text(payload, "title"),
            body=_text(payload, "body"),
            entities=entities,
            occurred_at=_parse_iso(_text(payload, "occurred_at"), fallback=received_at),
            received_at=received_at,
            raw=payload,
        )
    ]
