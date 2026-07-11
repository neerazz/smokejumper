# ADR-0011: Approvals on LangGraph interrupts + custom single-use tokens; HumanLayer rejected

**Status:** Accepted · 2026-07-10 · **Level:** L2

## Context
Privileged tool calls must suspend the run, ask a human in Slack, and resume exactly where
they stopped — durably. HumanLayer, the one OSS library purpose-built for Slack agent
approvals, was verified abandoned (repo README self-declares deprecated; org pivoted to a
different product; SDK was cloud-API-gated anyway).

## Decision
LangGraph `interrupt()` + PostgresSaver is the suspend/resume backbone; slack-bolt Block
Kit buttons are the UI; the token lifecycle — single-use, 30-min expiry, bound to
(thread_id, tool_call) — is custom code (~few hundred LOC).

## Options considered
1. **Interrupts + custom tokens (chosen).**
2. HumanLayer — dead and cloud-dependent. Rejected.
3. Custom pause queue outside the graph (park run state in our own table) — reinvents
   checkpointing and loses replayability.

## Trade-offs accepted
- **We own** the most security-sensitive custom code in the system (token minting/
  consumption); no library shares the liability. Mitigated: it's small, contract-tested,
  and every decision lands in the Flight Recorder.
- **We accepted** LangGraph-specific interrupt semantics (nodes re-execute from the top on
  resume ⇒ side effects must sit after the interrupt; `interrupt_before` for privileged
  nodes) as a permanent coding discipline in Intelligence.
- **We kept** durable approvals with zero extra infrastructure and a full audit trail free
  from the checkpointer.

## Revisit when
Approvals need to leave Slack (email/webhook approvers) — the broker grows a port; the
token model stays.
