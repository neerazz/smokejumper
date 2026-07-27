"""Turn an `AgentEvent` into a `Conclusion` (B6).

**This is deterministic triage, not an LLM investigation, and the distinction is
deliberate rather than a placeholder.** Every finding below is derived from data
the alert actually carries, so each one is checkable and the same input always
produces the same B6 — which is what makes `smokejumper replay` meaningful.

An LLM slots in behind `ports/model.py` without changing this module's contract:
`triage()` takes an event and returns a Conclusion, and a model-backed
implementation would return a richer one from the same inputs. Until a provider
credential exists, inventing a `root_caused` verdict from a language model we
cannot call would be the dishonest option; returning a real `needs_human` with
real evidence is the useful one.

The status ladder is intentionally conservative. Nothing here claims
`root_caused`, because a root cause requires evidence this stage does not have —
metric history, deploy timeline, log correlation. Those arrive with the read-tier
tools at M5, and the status ladder widens when the evidence does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from smokejumper.contracts.assignments import Budget, Finding
from smokejumper.contracts.conclusions import Conclusion, ConclusionStatus
from smokejumper.contracts.events import AgentEvent, Severity

# Severities that mean a human should look now. Below this, the incident is
# recorded and ticketed but not escalated.
ESCALATING = frozenset({Severity.CRITICAL, Severity.HIGH})

# Deterministic triage calls no tools and spends no tokens. Reporting a real zero
# rather than omitting the field keeps the Governor's arithmetic (SPEC 5.7) valid
# once model-backed specialists start reporting non-zero budgets beside these.
NO_SPEND = Budget(schema_version=1, tool_calls=0, tokens=0)


def _entity_summary(event: AgentEvent) -> str:
    if not event.entities:
        return "no entities were tagged on this alert"
    return ", ".join(f"{e.type}={e.id}" for e in event.entities)


def _findings(event: AgentEvent) -> list[Finding]:
    """Everything the alert itself establishes, each tied to its source."""
    findings: list[Finding] = [
        Finding(
            schema_version=1,
            agent="receiver",
            hypothesis=(
                f"{event.source.value} monitor {event.source_event_key} is firing at "
                f"{event.severity.value} severity"
            ),
            evidence=[f"event:{event.id}", f"fingerprint:{event.fingerprint}"],
            confidence=1.0,
            budget_spent=NO_SPEND,
        )
    ]

    if event.entities:
        findings.append(
            Finding(
                schema_version=1,
                agent="receiver",
                hypothesis=f"affected subject: {_entity_summary(event)}",
                evidence=[f"entity:{e.type}:{e.id}" for e in event.entities],
                confidence=1.0,
                budget_spent=NO_SPEND,
            )
        )

    # What we could not establish is itself a finding. Saying so keeps the
    # Conclusion honest about why it stops at needs_human.
    findings.append(
        Finding(
            schema_version=1,
            agent="triage",
            hypothesis=(
                "no root cause determined: this build has no metric history, deploy "
                "timeline, or log correlation to reason over"
            ),
            evidence=["capability:read-tier-tools-absent"],
            confidence=1.0,
            budget_spent=NO_SPEND,
        )
    )
    return findings


def _summary(event: AgentEvent, status: ConclusionStatus) -> str:
    lines = [
        f"**{event.title}**",
        "",
        f"- source: `{event.source.value}` monitor `{event.source_event_key}`",
        f"- severity: `{event.severity.value}`",
        f"- subject: {_entity_summary(event)}",
        f"- first seen: {event.occurred_at.isoformat()}",
        "",
        f"Triage reached `{status.value}`.",
    ]
    if event.body:
        lines += ["", "Alert detail:", "", "```", event.body.strip(), "```"]
    return "\n".join(lines)


def triage(event: AgentEvent, *, run_id: UUID | None = None) -> Conclusion:
    """Produce the Conclusion for one event.

    Deterministic: the same event always yields the same Conclusion, apart from
    `run_id` and timing, which is the property replay depends on.
    """
    started = datetime.now(tz=UTC)
    findings = _findings(event)

    # needs_human whenever a person should act now; inconclusive otherwise. Never
    # root_caused or mitigated -- neither is supportable from an alert alone, and
    # a Conclusion that overclaims is worse than one that stops early.
    status = (
        ConclusionStatus.NEEDS_HUMAN
        if event.severity in ESCALATING
        else ConclusionStatus.INCONCLUSIVE
    )

    return Conclusion(
        schema_version=1,
        run_id=run_id or event.id,
        fingerprint=event.fingerprint,
        status=status,
        # Confidence is in the *classification*, not in a root cause. High,
        # because severity and subject come straight from the alert.
        confidence=0.9 if event.entities else 0.6,
        summary_md=_summary(event, status),
        findings=findings,
        evidence_refs=[f"event:{event.id}", f"fingerprint:{event.fingerprint}"],
        proposed_actions=[f"inspect {e.type} {e.id}" for e in event.entities]
        or ["identify the affected subject: this alert carried no entity tags"],
        tokens_spent=0,
        wall_ms=max(1, int((datetime.now(tz=UTC) - started).total_seconds() * 1000)),
    )
