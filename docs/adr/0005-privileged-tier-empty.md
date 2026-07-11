# ADR-0005: Privileged tool tier ships empty; approval machinery built anyway

**Status:** Accepted · 2026-07-10 · **Level:** L1

## Context
The end-state vision includes gated remediations (restart service, scale deployment). The
approval flow (suspend → Slack approve/deny → single-use token) is architecturally load-
bearing, but shipping destructive tools in v1 of an unproven agent is how trust dies.

## Decision
Build and test the full gating machinery against a `demo_destructive_noop` tool enabled
only in tests. The production privileged tier ships with zero tools enabled.

## Options considered
1. **Machinery-yes, tools-no (chosen).**
2. Ship one "safe" remediation (e.g. rollback) — every remediation is unsafe somewhere.
3. Defer the whole approval flow to v2 — cheaper now, but retrofitting suspend/resume into
   a shipped graph is far costlier than building it in.

## Trade-offs accepted
- **We gave up** headline autonomy — v1 investigates and reports; it never fixes. The demo
  is less spectacular.
- **We accepted** carrying tested-but-unused machinery (dead weight risk) — bounded by the
  noop tool keeping the path exercised in CI.
- **We kept** a trust ramp: operators enable privileged tools one at a time, in their own
  manifest, after watching read-only behavior.

## Revisit when
Flight Recorder data shows ≥N incidents where a specific gated action was the obvious next
step and a human executed it manually — promote exactly that tool first.
