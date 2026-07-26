"""B2 — `AgentEvent`, the single input type intelligence accepts (SPEC §4)."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from smokejumper.contracts.base import Contract, Sha256Hex
from smokejumper.contracts.fingerprint import event_fingerprint


class EventSource(StrEnum):
    GRAFANA = "grafana"
    ALERTMANAGER = "alertmanager"
    DATADOG = "datadog"
    PAGERDUTY = "pagerduty"
    GENERIC = "generic"
    SLACK = "slack"
    SCHEDULED = "scheduled"


class EventKind(StrEnum):
    ALERT = "alert"
    CHAT = "chat"
    SCHEDULED = "scheduled"
    STORM = "storm"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Entity(Contract):
    """A thing the event is about, e.g. `type="service", id="checkout"`."""

    type: str = Field(min_length=1)
    id: str = Field(min_length=1)


class AgentEvent(Contract):
    """A normalized incident signal, whatever its source.

    `source_event_key` is the source's own identity for the signal (SPEC §4:
    Grafana/Alertmanager alert identity, Datadog monitor ID, PagerDuty dedup key,
    generic caller event ID, Slack thread timestamp, or recipe+window).
    """

    id: UUID
    source: EventSource
    kind: EventKind
    source_event_key: str = Field(min_length=1)
    fingerprint: Sha256Hex
    severity: Severity
    title: str
    body: str
    entities: list[Entity] = Field(default_factory=list)
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    dedupe_count: int = Field(default=1, ge=1)
    raw: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _fingerprint_is_the_canonical_one(self) -> AgentEvent:
        """Reject a fingerprint that is not the canonical hash of this event's identity.

        Without this the rule "never hash the title" is documentation; with it a
        normalizer that hashes anything else cannot construct an `AgentEvent`.
        """
        expected = event_fingerprint(
            self.source.value,
            self.source_event_key,
            [(entity.type, entity.id) for entity in self.entities],
        )
        if self.fingerprint != expected:
            raise ValueError(
                f"fingerprint {self.fingerprint} is not the canonical hash of "
                f"(source, source_event_key, entities); expected {expected}"
            )
        return self
