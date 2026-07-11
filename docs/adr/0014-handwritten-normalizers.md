# ADR-0014: Hand-written alert normalizers seeded from Alerta; no platform sidecar

**Status:** Accepted · 2026-07-10 · **Level:** L2

## Context
Falsification search confirmed no pip-installable library normalizes Grafana/Alertmanager/
Datadog/PagerDuty webhooks into a common model. What exists are full platforms with
embedded parsers: Keep (MIT core + ee/, a deployed FastAPI+Next.js product), Alerta
(Apache-2.0 server with clean per-source parsers in `alerta/webhooks/`), and Grafana
OnCall (archived June 2026 — dead).

## Decision
Hand-write per-source normalizers into `AgentEvent` (B2), seeding logic from Alerta's
Apache-2.0 parsers with attribution. Same for per-source HMAC signature verification
(each vendor's scheme differs; Alertmanager has none). CloudEvents was evaluated as an
envelope: sensible standard, but it doesn't remove per-source field mapping — optional,
not adopted for v1.

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
