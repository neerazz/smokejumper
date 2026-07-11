# ADR-0001: LangGraph checkpointing for durability; Temporal deferred

**Status:** Accepted · 2026-07-10 · **Level:** L1

## Context
Investigations are long-running (minutes), can suspend for human approval (up to 30 min),
and must survive process restarts. Durable-workflow engines (Temporal) and agent-framework
checkpointing (LangGraph + Postgres saver) both solve this.

## Decision
LangGraph with `langgraph-checkpoint-postgres` is the only durability layer in v1.
Temporal is explicitly deferred, not rejected.

## Options considered
1. **LangGraph checkpointing (chosen)** — state persists in the Postgres we already run.
2. Temporal — stronger guarantees (retries, timers, heartbeats, versioned workflows) but a
   second stateful service + worker fleet + its own operational discipline.
3. Celery/queue-with-retries — durability by convention only; interrupt/resume unsupported.

## Trade-offs accepted
- **We gave up** engine-grade retry/timer semantics: retries, backoff, and the approval-expiry
  sweeper are hand-written scheduler code instead of engine primitives.
- **We gave up** workflow versioning for in-flight runs; a deploy during a suspended run must
  keep graph shape compatible (mitigated: runs are short except approval waits).
- **We kept** a one-service deployment a solo maintainer can operate — the deciding factor
  for a side-project SRE tool that must itself not become an ops burden.

## Revisit when
Runs need cross-day durability, fan-out beyond one process, or in-flight migration —
that's the Temporal trigger (2026-07-10 research consensus: "LangGraph-only durability for v1").
