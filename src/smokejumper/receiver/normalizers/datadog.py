"""Datadog webhook -> `AgentEvent` (B2).

A Datadog webhook body is whatever the operator's payload template says, built
from Datadog's `$VARIABLES`. This normalizer reads the variable names Datadog
documents, so the operator's template is the contract:

    {"alert_id": "$ALERT_ID", "alert_transition": "$ALERT_TRANSITION",
     "alert_type": "$ALERT_TYPE", "priority": "$PRIORITY",
     "title": "$EVENT_TITLE", "body": "$EVENT_MSG", "tags": "$TAGS",
     "date": "$DATE", "aggreg_key": "$AGGREG_KEY", "metric": "$METRIC"}

Two mappings carry real weight and are not obvious:

`source_event_key` is `$ALERT_ID`, the monitor ID (SPEC 4). It is deliberately
not `$AGGREG_KEY`: Datadog rotates the aggregation key per alert *episode*, so
keying on it would make every re-trigger of the same monitor a new incident and
defeat the dedupe window it is supposed to feed.

Entities come only from identity-bearing tags, because entities feed the
fingerprint. Datadog attaches volatile tags to the same monitor across
deliveries, and letting one of those in would change the fingerprint mid-incident
and open a second ticket for it. The allowlist is the mechanism.
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

# Tag keys that identify *what* is broken. Anything else Datadog sends is
# context, and context does not belong in an identity hash.
IDENTITY_TAG_KEYS = frozenset(
    {
        "service",
        "host",
        "env",
        "cluster",
        "cluster_name",
        "database",
        "table",
        "region",
        "availability-zone",
        "kube_namespace",
        "kube_deployment",
        "queue",
        "topic",
    }
)

# Datadog's own priority scale is the most specific severity signal available.
_PRIORITY_SEVERITY = {
    "P1": Severity.CRITICAL,
    "P2": Severity.HIGH,
    "P3": Severity.MEDIUM,
    "P4": Severity.LOW,
    "P5": Severity.INFO,
}

# Fallback when the monitor sets no priority. `error` is not mapped to CRITICAL:
# without a priority Datadog gives no way to distinguish a paging alert from a
# routine one, and inventing CRITICAL would put the storm brake (SPEC 5.7) under
# the control of a guess.
_ALERT_TYPE_SEVERITY = {
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "success": Severity.INFO,
    "info": Severity.INFO,
}

# Transitions that mean "this incident is over". Recovery is normalized and
# recorded but must not open an investigation (SPEC 5.1).
RECOVERY_TRANSITIONS = frozenset({"Recovered", "recovered"})


class UnparseablePayload(ValueError):
    """The body is not a Datadog webhook we can normalize, so it is quarantined."""


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return "" if value is None else str(value).strip()


def parse_tags(raw: object) -> list[str]:
    """Datadog sends `$TAGS` as one comma-separated string; a JSON template sends a list."""
    if isinstance(raw, str):
        candidates = raw.split(",")
    elif isinstance(raw, list):
        candidates = [str(item) for item in raw]
    else:
        return []
    return [tag.strip() for tag in candidates if tag.strip()]


def tag_entities(tags: list[str]) -> list[Entity]:
    """Identity-bearing `key:value` tags, deduplicated.

    Sorted and deduplicated so two deliveries of one alert produce the same
    entity set, which is what keeps the fingerprint stable.
    """
    seen: set[tuple[str, str]] = set()
    for tag in tags:
        key, separator, value = tag.partition(":")
        if not separator:
            continue
        key, value = key.strip().lower(), value.strip()
        if key in IDENTITY_TAG_KEYS and value:
            seen.add((key, value))
    return [Entity(type=key, id=value) for key, value in sorted(seen)]


def severity_of(payload: dict[str, Any]) -> Severity:
    """Datadog priority first, alert type second, `info` last."""
    priority = _text(payload, "priority").upper()
    if priority in _PRIORITY_SEVERITY:
        return _PRIORITY_SEVERITY[priority]
    return _ALERT_TYPE_SEVERITY.get(_text(payload, "alert_type").lower(), Severity.INFO)


def occurred_at_of(payload: dict[str, Any], *, received_at: datetime) -> datetime:
    """`$DATE` is epoch milliseconds. Fall back to arrival, never to a guess.

    A malformed date must not fail the request: losing the alert is worse than
    losing a few seconds of timestamp precision, and `received_at` is always
    truthful about when we saw it.
    """
    raw = payload.get("date")
    try:
        milliseconds = int(str(raw))
    except (TypeError, ValueError):
        return received_at
    if milliseconds <= 0:
        return received_at
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def is_recovery(payload: dict[str, Any]) -> bool:
    """True when this delivery says the incident ended."""
    return _text(payload, "alert_transition") in RECOVERY_TRANSITIONS


def normalize(payload: dict[str, Any], *, received_at: datetime) -> AgentEvent:
    """Build the `AgentEvent` for one Datadog webhook delivery.

    Raises `UnparseablePayload` when `alert_id` is absent, because without the
    monitor ID there is no stable incident identity — and an event whose
    fingerprint cannot be trusted would corrupt the dedupe window rather than
    just being unhelpful.
    """
    if not isinstance(payload, dict):
        raise UnparseablePayload("body is not a JSON object")

    alert_id = _text(payload, "alert_id")
    if not alert_id:
        raise UnparseablePayload("alert_id is required: it is the monitor identity")

    entities = tag_entities(parse_tags(payload.get("tags")))
    title = _text(payload, "title") or f"Datadog monitor {alert_id}"

    return AgentEvent(
        id=uuid4(),
        source=EventSource.DATADOG,
        kind=EventKind.ALERT,
        source_event_key=alert_id,
        fingerprint=event_fingerprint(
            EventSource.DATADOG.value,
            alert_id,
            [(entity.type, entity.id) for entity in entities],
        ),
        severity=severity_of(payload),
        title=title,
        body=_text(payload, "body"),
        entities=entities,
        occurred_at=occurred_at_of(payload, received_at=received_at),
        received_at=received_at,
        raw=payload,
    )
