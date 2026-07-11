# ADR-0012: JSONL flight recorder as audit source of truth; observability platforms deferred

**Status:** Accepted · 2026-07-10 · **Level:** L2 · Sponsor requirement (file-based, streamable, no retention policy)

## Context
Every event, LLM call, tool call, gate, and action must be auditable and replayable.
Research surveyed Langfuse (richest, but self-host = 6 services incl. ClickHouse), Opik
(Apache-2.0, compose stack), Phoenix (ELv2, in-process), OpenLLMetry (library-only OTel).

## Decision
Append-only JSONL files in the log directory (dated, timestamp-suffixed per process start)
are the authoritative audit record; an in-process broadcast channel makes them streamable;
Postgres keeps only a run→file/offset index. No observability platform in v1; at most
library-only OTel spans (OpenLLMetry) as optional debug telemetry.

## Options considered
1. **JSONL SoT + optional OTel (chosen).**
2. Langfuse/Opik as the audit store — a queryable UI, but the audit record would live inside
   a third-party platform's schema and a heavy service stack.
3. Postgres `audit_events` table as SoT (original draft) — queryable, but invites retention
   policy and DB bloat; sponsor explicitly wanted files.

## Trade-offs accepted
- **We gave up** queryability — grep/jq replaces SQL over audit events; anything needing an
  index must be planned into the `runs` table.
- **We gave up** a trace UI in v1 — debugging is `smokejumper logs --follow` and replay,
  not flamegraphs.
- **We kept** an audit record that is trivially archivable, tamper-evident by append-only
  convention, dependency-free to read in 20 years, and never subject to a platform's
  retention/license terms.

## Revisit when
A second operator asks "show me all runs where X" twice — that's the sign to add Opik
(cleanest license) as a *read-side* consumer, with JSONL still authoritative.
