# ADR-0016: Local observability stack behind compose profiles; SaaS sources replayed

**Status:** Accepted · 2026-07-25 · **Level:** L2 · **Amended** 2026-07-26 (Grafana and the
`fixtures` profile both dropped — see "Amended" below)

## Context
v1's alert sources (Grafana, Datadog, PagerDuty, generic) and its read-tier tool backends
(`log search`, `metric query`) were specified without any local equivalent. Two problems fell
out of that. First, end-to-end verification depended entirely on hand-crafted webhook
fixtures — nothing ever fired a *real* alert at the Receiver. Second, and worse, `log search`
and `metric query` were named as v1 read tools with **no backend behind them at all**, so
specialist investigation would have been stubbed from the start.

A third issue is only visible once you try to fix the first two: Datadog and PagerDuty are
SaaS. There is no local Datadog. Running `datadog/agent` requires an account and API key and
ships telemetry to their cloud, and getting their webhooks back to a laptop needs a public
tunnel. Any "just add it to compose" plan silently assumes otherwise.

## Decision
Add a **`lab` compose profile** with prometheus + alertmanager, loki + promtail, and a
`faultbox` fault-injection app. Recorded Datadog/PagerDuty payloads are POSTed at the Receiver by
a `fixtures replay` CLI command. Default `docker compose up` remains postgres + redis + app.
Prometheus becomes the `metric query` backend; Loki becomes the `log search` backend.

## Amended 2026-07-26: no Grafana, no `fixtures` profile
Two pieces of the original profile set earned removal, and both for the same reason — a container
that added no coverage.

**Grafana.** The original `lab` profile ran Grafana OSS as a second local alert source.
Alertmanager already fires a real HTTP webhook at the Receiver, so the second source added a
container without adding coverage: what the Grafana normalizer has to get right is the *payload
shape*, and that is tested by golden fixtures and by replay, exactly like Datadog and PagerDuty.
Grafana remains a supported alert source; it is simply not run locally.

**The `fixtures` profile.** Its only service was the app image running one CLI command, which
acceptance invokes directly. That is a compose service, a profile, and an environment-gating rule
in exchange for nothing. The recorded corpus — the part that actually does the work, since the
golden per-source tests read it — is untouched.

Loki stays. `log search` still needs a real backend, and losing it would return that tool to the
unbacked state this record exists to fix.

## Options considered
1. **Profiles + Loki + fixture replay for SaaS (chosen).**
2. ELK (Elasticsearch + Logstash + Kibana) as the log backend — the stack most teams already
   know, and Logstash's parsing is genuinely richer. Rejected on footprint: Elasticsearch
   alone wants 1–2GB of heap, Logstash another 1GB+, Kibana ~500MB. That is 4GB+ before the
   app starts, on a project whose adoption story is "clone and compose up".
3. All lab services in the default compose file — simplest to document, but turns a
   3-service default into ~10 and spends ADR-0002's one-command onboarding benefit.
4. Real Datadog/PagerDuty agents in compose — impossible without accounts, keys, and an
   inbound tunnel; would make a paid SaaS account a prerequisite for running the test suite.
5. No local stack, fixtures only (status quo) — cheapest, but leaves the tool backends
   unbacked and makes "is the conclusion correct" permanently unanswerable.

## Trade-offs accepted
- **We gave up** Logstash/Elasticsearch parsing and query power for footprint. Loki's LogQL
  is weaker at ad-hoc analytics; for "fetch the logs around this incident window" it is
  sufficient, and that is the only query shape `log search` needs.
- **We gave up** true fidelity for Datadog and PagerDuty: we test our normalizers and HMAC
  verification against *recorded* payloads, so a vendor changing their webhook shape is
  caught by fixture staleness, not by the lab. §8's golden fixtures are the tripwire, and
  ADR-0014 already accepted payload-drift maintenance.
- **We accepted** a second compose invocation to document (`--profile lab`) as the price of
  keeping the default trivial.
- **We kept** — and this is the reason the ADR exists at all — a path to *mechanically
  scored* conclusions. A faultbox-injected fault has known ground truth, so a run's
  Conclusion can be graded automatically instead of eyeballed. The lab is the eval-corpus
  factory, not a developer convenience.

## Revisit when
A supported alert source has no local equivalent *and* its payloads drift often enough that
fixture staleness bites twice — then consider vendoring that vendor's own test-event
generator. Separately: if the `lab` profile stops fitting comfortably on a laptop, split it
into `lab-metrics` and `lab-logs` rather than trimming fidelity.
