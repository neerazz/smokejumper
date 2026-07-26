# ADR-0014: Hand-written alert normalizers seeded from Alerta; no platform sidecar

**Status:** Accepted · 2026-07-10 · **Level:** L2 · **Amended 2026-07-26** ("per-source HMAC" was
wrong for Datadog, which signs nothing — found while implementing the normalizer; current contract:
SPEC §11.5.6)

## Context
Falsification search confirmed no pip-installable library normalizes Grafana/Alertmanager/
Datadog/PagerDuty webhooks into a common model. What exists are full platforms with
embedded parsers: Keep (MIT core + ee/, a deployed FastAPI+Next.js product), Alerta
(Apache-2.0 server with clean per-source parsers in `alerta/webhooks/`), and Grafana
OnCall (archived June 2026 — dead).

## Decision
Hand-write per-source normalizers into `AgentEvent` (B2), seeding logic from Alerta's
Apache-2.0 parsers with attribution. Same for per-source verification, using whatever
scheme each vendor actually provides. CloudEvents was evaluated as an envelope: sensible
standard, but it doesn't remove per-source field mapping — optional, not adopted for v1.

*Amended 2026-07-26.* This originally said "per-source HMAC signature verification (each
vendor's scheme differs; Alertmanager has none)". Building the Datadog normalizer showed
that framing was too optimistic: **Datadog documents no request signing at all** — its
webhooks are operator-defined payloads with optional custom headers, so there is nothing to
compute an HMAC over. Verification there is a constant-time comparison of a shared bearer
token, which is weaker and replayable. So the axis is not "every vendor signs, differently"
but "signing ranges from a real HMAC (our own generic endpoint) through a bearer token
(Datadog) to nothing at all (Alertmanager, network-allowlisted instead)". The
hand-write-per-source decision is unchanged and is if anything reinforced: a library
assuming a uniform signature scheme could not have expressed this.

## Options considered
1. **Hand-write, seed from Alerta (chosen)** — parsers are small, stable payload mappings.
2. Run Keep or Alerta as a normalization sidecar — a whole product deployed to reuse ~500
   lines of parsing; operational tail wags the dog.
3. Wait for/adopt CloudEvents alerting semantics — envelope only; alert semantics
   (severity, firing/resolved, fingerprint) still ours.

## Trade-offs accepted
- **We own** payload-drift maintenance for every supported source — vendors change webhook
  shapes; golden fixtures per source (§8) are the tripwire.
- **We gave up** Keep's breadth (dozens of providers, bi-directional) — Smokejumper adds
  sources one at a time, on demand.
- **We kept** a Receiver with zero heavyweight dependencies, aligned with ADR-0003's
  deterministic-ingress requirement.

## Revisit when
Supported sources exceed ~8 and parser maintenance becomes a real tax — re-evaluate
vendoring Keep's provider layer wholesale at that point.
