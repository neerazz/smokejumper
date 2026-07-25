# Architecture Decision Records

One record per significant decision, with the options considered, the trade-off we knowingly
accepted, and the condition that should reopen it. Format: lightweight MADR.

**Levels.** **L1** = container architecture (the blocks and the boundaries between them).
**L2** = component and library design inside a block.

A new ADR is required whenever a decision (a) crosses a boundary contract, (b) adds a runtime
dependency, or (c) trades away a capability. **Supersede, don't edit:** a changed decision gets
a new ADR linking back. An ADR that *extends* an earlier one without reversing it says so in its
header (`Amends` / `Strengthens`).

Numbering is chronological, not ordered by importance — read [0015](0015-agent-framework-langgraph.md)
and [0003](0003-deterministic-edges.md) first if you want the two decisions that shape everything
else.

## L1 · Container architecture

**[0015 · Intelligence framework: LangGraph](0015-agent-framework-langgraph.md)**
Picks LangGraph over CrewAI, AutoGen, PydanticAI, the OpenAI Agents SDK, and plain Python. The
deciding requirement was the approval flow: suspend a half-finished multi-agent run, survive a
restart, resume on a Slack button. That is native to LangGraph and DIY everywhere else. Accepts
LangChain-ecosystem churn and pinned-version discipline in exchange, and contains the blast
radius by letting Intelligence talk to the world only through B2 in and B6 out.

**[0001 · LangGraph checkpointing for durability; Temporal deferred](0001-langgraph-not-temporal.md)**
Investigations run for minutes and can suspend 30 minutes for approval, so they need durable
state. Uses the Postgres checkpointer we already run instead of adding Temporal. Gives up
engine-grade retry/timer semantics and in-flight workflow versioning; keeps a one-service
deployment a solo maintainer can operate.

**[0002 · One Postgres 16 + pgvector for all state](0002-one-postgres.md)**
Relational state, vectors, graph edges, and checkpoints all live in a single database rather
than best-of-breed stores. Gives up native graph traversal performance and — the most expensive
consequence — rules out Graphiti as a dependency. Keeps one backup story, transactional joins
across memory and runs, and a compose file a newcomer can run in one command.

**[0003 · No LLM in Receiver or Actions; B6 is the determinism boundary](0003-deterministic-edges.md)**
Models run only inside Intelligence. Ingress (normalize, fingerprint, dedupe, coalesce) and
egress (create-vs-update, receipts) are pure deterministic code, and nothing downstream of the
`Conclusion` contract may call a model. Gives up semantic alert grouping at ingest; keeps
reproducibility, bounded cost under storms, and an egress the audit log can fully explain.

**[0004 · Hexagonal ports with loud v1 stubs](0004-hexagonal-ports.md)**
Auth, governance, tenancy, model provider, platform, channel, ticketing, and memory are all
interfaces so the OSS core never needs a fork to gain real auth or tenancy. Accepts more
indirection than a single-tenant v1 strictly needs. Its accepted risk — that stubs normalize
insecurity if deployed carelessly — is closed later by [0018](0018-layered-environment-config.md).

**[0005 · Privileged tool tier ships empty; approval machinery built anyway](0005-privileged-tier-empty.md)**
The full gating path (suspend → approval → single-use token → execute) is built and tested
against a noop tool, but production ships zero privileged tools. Gives up headline autonomy —
v1 investigates and reports, it never fixes — and accepts carrying tested-but-unused machinery,
because retrofitting suspend/resume into a shipped graph costs far more than building it in.

## L2 · Component and library design

**[0006 · redis-py Streams directly; no task-queue framework](0006-redis-streams-direct.md)**
Uses XADD/XREADGROUP/XACK/XAUTOCLAIM directly rather than taskiq, arq, streaq, or celery. Costs
us ~200 lines of ack/claim/redelivery policy we must get right, with idempotency by `event.id`
as the safety net; buys exact control of consumer-group semantics, which the storm brake
manipulates directly.

**[0007 · Provider-agnostic LLM via init_chat_model config](0007-model-provider-config.md)**
A sponsor hard requirement: swap Anthropic, OpenAI, Gemini, or a local model per deployment
with no code change. A `ModelProvider` port wraps LangChain provider strings, configured per
role. Gives up provider-native features at the call site (prompt caching, provider-specific
tool modes) and accepts that prompts tuned on one provider merely *run* on others.

**[0008 · Slack Socket Mode; ChannelAdapter port, Slack-only v1](0008-slack-socket-mode-channel-port.md)**
Socket Mode means no public HTTPS endpoint, so adopters can run this on a laptop or homelab.
Gives up horizontal scaling of the Slack listener and an installable OAuth distribution flow.
Telegram and email are designed-for behind the same port but deliberately unbuilt.

**[0009 · Hand-rolled bi-temporal memory behind MemoryPort](0009-handrolled-bitemporal-memory.md)**
Copies Graphiti's published bi-temporal data model (`valid_at`/`invalid_at` +
`created_at`/`expired_at`) into Postgres tables rather than adopting Graphiti (needs a graph DB,
violates [0002](0002-one-postgres.md)) or Cognee (dev-tagged releases, recent opt-in temporal
mode). Gives up free entity extraction, dedup, and graph reasoning — the Distiller now owes all
three by hand. Keeps a version-stable schema for the component whose correctness *is* the
product's credibility.

**[0010 · FastMCP middleware as the governance seam, with defense in depth](0010-fastmcp-middleware-governance.md)**
Tool tiering runs in FastMCP's `on_call_tool` hook — the only embeddable in-process Python
option, since every dedicated MCP gateway is a standalone proxy service. Enforcement is
duplicated in our own tool executor so a third-party hook is never the only check. Extended by
[0017](0017-mcp-domain-single-gateway.md), which found a path that bypassed the seam entirely.

**[0011 · Approvals on LangGraph interrupts + custom single-use tokens](0011-approvals-langgraph-interrupts.md)**
`interrupt()` plus the Postgres saver provides durable suspend/resume; Block Kit buttons are the
UI. The token lifecycle (single-use, 30-minute expiry, bound to thread and tool call) is our
code because HumanLayer — the one purpose-built library — self-declares deprecated. We own the
most security-sensitive custom code in the system, and accept LangGraph's node-re-execution
semantics as permanent coding discipline.

**[0012 · JSONL flight recorder as audit source of truth](0012-jsonl-audit-source-of-truth.md)**
Append-only dated JSONL files are authoritative; Postgres holds only a run → file/offset index.
Gives up queryability (grep and jq replace SQL) and a trace UI, in exchange for an audit record
that is trivially archivable, dependency-free to read in twenty years, and never subject to a
platform's retention or license terms. Its governing rule — no platform owns the record — later
drives [0020](0020-prompt-registry-in-git.md). Its "no trace UI in v1" clause is amended by
[0019](0019-observability-otel-phoenix.md).

**[0013 · Hand-rolled TicketingPort; Linear via direct GraphQL](0013-ticketingport-adapters.md)**
Falsification confirmed no OSS Python library unifies Linear + GitHub + Jira + Asana, and
commercial unified APIs mean incident data egress. Four provider-neutral methods with a shared
conformance suite every adapter must pass. We own adapter maintenance forever, including Linear
schema drift with no SDK cushion.

**[0014 · Hand-written alert normalizers seeded from Alerta](0014-handwritten-normalizers.md)**
No pip-installable library normalizes Grafana/Alertmanager/Datadog/PagerDuty webhooks — what
exists are whole platforms with parsers inside them. We hand-write per-source normalizers and
HMAC verification, seeding logic from Alerta's Apache-2.0 parsers with attribution, rather than
deploying Keep or Alerta as a sidecar to reuse ~500 lines. We own payload-drift maintenance;
golden fixtures are the tripwire.

**[0016 · Local observability stack behind compose profiles](0016-local-observability-stack.md)**
Adds a `lab` profile (Prometheus + Alertmanager, Grafana, Loki + Promtail, a faultbox) so alert
sources and tool backends are real locally — `log search` and `metric query` previously had no
backend at all. Datadog and PagerDuty are SaaS with no local equivalent, so a `fixtures`
replayer posts recorded payloads instead. Loki over ELK on footprint (~200MB vs 4GB+). The real
payoff: an injected fault has known ground truth, making the lab the eval-corpus factory.

**[0017 · One MCP domain: single gateway, single tier manifest](0017-mcp-domain-single-gateway.md)**
Collapses `hub/` and the separate federated client in `knowledge/` into one `mcp/` package.
This was not cosmetic — the two-client split meant knowledge federation reached external servers
without ever crossing the tier check, contradicting [0010](0010-fastmcp-middleware-governance.md)'s
defense-in-depth thesis. Rejects per-server tier declarations on security grounds: a tool must
not be able to declare its own tier next to itself.

**[0018 · Layered local/dev/prod config; prod fails closed](0018-layered-environment-config.md)**
One validated settings object assembled from `base.yaml` → `<env>.yaml` → env vars → flags,
selected by `SMOKEJUMPER_ENV`. Reserves "environment" for local/dev/prod and "compose profile"
for service selection, because the two were about to share a word. Closes
[0004](0004-hexagonal-ports.md)'s open risk: prod now refuses to boot with stub ports, refuses
to run without a spend ceiling, and refuses the `lab`/`fixtures` profiles.

**[0019 · OpenTelemetry seam; Arize Phoenix as default backend](0019-observability-otel-phoenix.md)**
Instrument once with OTel/OpenInference inside the model port and MCP gateway, so the backend
is a config value — the same pattern as [0007](0007-model-provider-config.md) and
[0009](0009-handrolled-bitemporal-memory.md). Phoenix is the default (single container,
eval-first evaluators aimed at whether a Conclusion was grounded); Langfuse is a documented
swap. Accepts a non-OSI license (ELv2, source-available) for the default. LangSmith rejected:
proprietary, no practical self-host, and it would ship production log content to a vendor.

**[0020 · Prompts in git as immutable versions](0020-prompt-registry-in-git.md)**
`prompts/` is the source of truth; the agent registry references `agents/<name>@vN` instead of
inlining prompt text, and every `llm_call` records `prompt_ref` + `prompt_sha256`. Without that
stamp a regression cannot be traced to a prompt change and replay cannot assert it is running
the prompt it recorded. Platform prompt registries were rejected as the store for the same
reason [0012](0012-jsonl-audit-source-of-truth.md) rejected platform audit storage.

## Reading paths

- **New contributor:** 0015 → 0003 → 0004 → 0002, then the SPEC.
- **Auditing the security model:** 0005 → 0010 → 0017 → 0011 → 0018.
- **Understanding memory and learning:** 0002 → 0009 → 0012 → 0016.
- **Changing prompts or debugging a bad conclusion:** 0020 → 0019 → 0012.
