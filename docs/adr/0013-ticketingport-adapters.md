# ADR-0013: Hand-rolled TicketingPort; Linear adapter via direct GraphQL

**Status:** Accepted · 2026-07-10 · **Level:** L2 · Sponsor requirement (extensible; Linear first, then GitHub/Jira/Asana)

## Context
Research falsification confirmed: no OSS Python library unifies Linear + GitHub + Jira +
Asana (ticketutil exists but supports JIRA/RT/Redmine/Bugzilla/ServiceNow — wrong set);
commercial unified APIs (Merge, Unified.to) are SaaS with data egress. Linear has no
official Python SDK; the community wrapper is stale (2 releases, 14 months old).

## Decision
Hand-write `TicketingPort` (create / update / find_open_by_fingerprint / close over
provider-neutral TicketDraft/Update/Ref models) with a shared conformance test suite.
v1 adapter: Linear via direct GraphQL (httpx/gql). Later adapters wrap verified SDKs:
githubkit (GitHub), atlassian-python-api (Jira), official asana.

## Options considered
1. **Custom port + per-provider adapters (chosen).**
2. Depend on community linear-api — single-author, stale; a dead dependency at our egress.
3. Unified SaaS API — instant breadth, but incident data flows through a third party and
   the OSS project gains a commercial prerequisite. Rejected outright.

## Trade-offs accepted
- **We own** adapter maintenance forever, including Linear GraphQL schema drift with no SDK
  cushion — bounded by the tiny surface (4 methods) and conformance tests that make drift
  loud.
- **We gave up** breadth-on-day-one: one provider at launch.
- **We kept** provider choice as config (`ticketing.provider`), no data egress, and — per
  the deliberate PyGithub→githubkit call — permissive licenses and async support in the
  adapter layer.

## Revisit when
An official Linear Python SDK ships (swap the adapter internals; port unchanged).
