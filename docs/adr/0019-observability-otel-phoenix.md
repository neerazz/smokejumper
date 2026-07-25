# ADR-0019: OpenTelemetry as the instrumentation seam; Arize Phoenix as the default trace backend

**Status:** Accepted · 2026-07-25 · **Level:** L2 · **Amends** [ADR-0012](0012-jsonl-audit-source-of-truth.md) (un-defers the trace UI; JSONL remains authoritative)

## Context
ADR-0012 deferred every observability platform to v2 and named Opik as the likely pick "if
Smokejumper is ever deployed fleet-wide." That deferral is now being reversed deliberately,
because debugging a multi-agent run from JSONL with `jq` is the weakest part of the
developer experience, and because the project's largest open gap is *measuring whether
conclusions are correct* — which is an evaluation problem, not a logging one.

Facts re-verified 2026-07-25 (the 2026-07-10 sweep is partially stale):

- **Arize Phoenix** — Elastic License 2.0, **source-available, not OSI open source**. Self-hosts
  as a *single process* (`pip install arize-phoenix`, one Docker container, or Helm).
  OpenTelemetry-native using OpenInference semantic conventions. No event caps. Eval-first:
  ships hallucination, faithfulness, retrieval-relevance, and QA-correctness evaluators, plus
  embedding-drift visualization. SQLite by default, Postgres for production.
- **Langfuse** — MIT core (`ee/` under a separate enterprise license), so OSI-clean. Self-host
  is **web + worker + Postgres + ClickHouse + Redis/Valkey + S3-compatible storage**. Ingests
  OTel via an OTLP endpoint. Best-in-class prompt management with versions, labels, and
  runtime fetch. Acquired by ClickHouse in January 2026.
- **LangSmith** — proprietary; self-host is gated behind an enterprise sales conversation.
  Deepest LangGraph trace fidelity of anything available.
- **OpenLLMetry** — Apache-2.0, library-only OTel instrumentation, no service.

## Decision
Two layers, deliberately separated.

1. **Instrumentation is OpenTelemetry** using OpenInference conventions, emitted from inside
   the `ModelProvider` port and the MCP gateway. This is the seam; the backend is a config
   value, exactly as ADR-0007 did for model providers and ADR-0009 for the memory store.
2. **The default backend is Phoenix**, shipped behind an **`obs` compose profile**. Langfuse
   is documented as a supported swap (repoint the OTLP exporter; no code change).

**JSONL remains the audit source of truth.** The platform is a read-side consumer that may be
absent, wiped, or replaced without affecting the audit record or replay. ADR-0012's core
holds; only its "no trace UI in v1" clause is amended.

## Options considered
1. **OTel seam + Phoenix default behind a profile (chosen).**
2. LangSmith — the deepest LangGraph node-level traces, which is genuinely tempting given
   ADR-0015. **Rejected on two independent grounds:** it is proprietary with no practical
   self-host, and it would ship production log content — the exact payloads a redaction layer
   is supposed to protect — to a third-party cloud. An MIT self-hostable SRE tool cannot have
   a proprietary SaaS as its default telemetry sink.
3. Langfuse as the default — better license (MIT vs ELv2) and better prompt management.
   Rejected on footprint: six services including ClickHouse is larger than all of
   Smokejumper's own infrastructure combined, against ADR-0002's one-command onboarding. Its
   prompt-management advantage is also neutralized by ADR-0020, which keeps prompts in git.
4. Opik (ADR-0012's original pick) — Apache-2.0 and eval-capable, but a compose stack rather
   than a single process, and weaker OTel-native positioning than Phoenix.
5. Stay deferred, JSONL + `jq` only — cheapest, and leaves the correctness gap with no tooling
   at exactly the moment the design is adding a retrieval loop that makes runs harder to read.
6. Own the stack: OTel spans into our own Postgres, dashboards in the Grafana we already run
   in `lab`. Genuinely attractive for footprint, rejected because building a trace UI is a
   product, not a side quest.

## Trade-offs accepted
- **We accepted a non-OSI license for the default.** ELv2 is source-available; it forbids
  offering Phoenix as a managed service to third parties. For self-hosting your own tracing it
  changes nothing, but it must not be described as "open source," and an adopter whose
  procurement requires OSI licenses needs the Langfuse swap. **The OTel seam is what makes that
  swap a config change** — which is the entire reason the seam is layer 1 of this decision.
- **We gave up** LangGraph-native trace fidelity. Generic OTel spans of graph nodes are less
  informative than LangSmith's checkpoint-aware view, and we will occasionally wish we had it.
- **We accepted** that Phoenix's single-process default (SQLite) will need moving to Postgres
  before it is useful at volume, and that its UI degrades past a few thousand accumulated
  traces.
- **We kept** an audit record that owes nothing to a vendor, a backend that is a config value,
  and — the reason this lands now rather than in v2 — Phoenix's evaluator library sitting
  directly on the problem of whether a Conclusion was actually grounded.

## Revisit when
Procurement at a real adopter rejects ELv2 (→ make Langfuse the documented default; the
instrumentation does not change), or trace volume outgrows a single Phoenix process (→ Langfuse
and its ClickHouse backend become the scaling answer), or OTel GenAI semantic conventions
stabilize enough that OpenInference adds nothing (→ drop to plain OTel).
