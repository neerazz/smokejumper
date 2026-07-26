# ADR-0021: agentgateway sidecar proxies LLM and MCP traffic; application policy remains authoritative

**Status:** Accepted · 2026-07-25 · **Level:** L1 · **Amends** [ADR-0010](0010-fastmcp-middleware-governance.md) and [ADR-0017](0017-mcp-domain-single-gateway.md)

## Context

The original design deliberately rejected a standalone MCP proxy to preserve a one-process app.
That choice left two needs inside Smokejumper code:

1. LLM provider credentials, protocol normalization, routing/failover, token accounting, and
   network telemetry.
2. MCP transport, backend credentials/TLS, federation/multiplexing, network authorization, and
   network telemetry.

Neeraj explicitly wants a real gateway proxy. `agentgateway/agentgateway` is an Apache-2.0 Rust
HTTP/gRPC proxy for HTTP, LLM, MCP, and A2A traffic. Its standalone mode supports virtual LLM
models, MCP multiplexing, CEL authorization over tool names/arguments, per-target backend auth,
rate limits, Prometheus metrics, and OTLP traces.

A local source/runtime spike pinned v1.3.1 (`dbaaf7ed73671e7aec9195e35e7f726c0b14b84a`):

- release binary SHA-256 matched
  `d3b507d31a2197a2deecdaac32734af37ee5d0ecb060a06104be0086340c1e66`;
- ordinary HTTP proxy request returned 200;
- MCP initialize returned 200 with a session ID, and `tools/list` exposed 13 tools;
- an `mcpAuthorization` CEL rule reduced discovery to the single allowed `echo` tool;
- admin UI and Prometheus metrics endpoints responded; shutdown drained listeners cleanly.

v1.4.0-beta.1 existed at evaluation time. It is not the v1 dependency: Smokejumper starts from
stable v1.3.1 and upgrades only through a compatibility test + image-digest change.

## Decision

Add **agentgateway as a core sidecar/data-plane service**. The default Compose stack becomes
`app + agentgateway + postgres + redis`.

### LLM path

`ModelProvider` calls stable virtual model names (`smokejumper-worker`,
`smokejumper-synthesis`, and `smokejumper-embedding`) on agentgateway's internal LLM listener.
Agentgateway owns upstream provider credentials, provider protocol details, failover/routing,
outer token rate limits, cost metrics, and provider-facing TLS. Smokejumper still owns the
per-run budget ledger, prompt identity, model response recording, and B8 audit event.

### MCP path

FastMCP remains the runtime used to implement Smokejumper's own MCP servers. Those servers are
mounted on an app-internal Streamable HTTP endpoint that is reachable only by agentgateway.
Agentgateway multiplexes those targets with configured remote MCP servers into one virtual MCP
endpoint; tool names are target-prefixed.

Smokejumper's MCP client connects only to that virtual endpoint. No application package opens a
direct remote MCP connection.

### Policy ownership and approval

`src/smokejumper/mcp/manifest.yaml` remains the sole semantic tool→tier source of truth. A
deterministic generator emits `compose/agentgateway/config.generated.yaml` and CEL allow rules
from that manifest and the federated descriptors. CI fails on generated-config drift.

Enforcement is deliberately layered:

1. agentgateway hides/denies tools with generated `mcpAuthorization` rules;
2. Smokejumper's executor re-checks the tier from the manifest;
3. privileged calls interrupt LangGraph and require the B5 Slack/single-use-token path.

Agentgateway does **not** replace the stateful approval broker. The production privileged tier
still ships empty; the test noop proves the flow.

### Network and audit boundaries

- LLM (`4000`) and MCP (`3000`) listeners are Compose-internal by default.
- Admin UI (`15000`) binds to loopback only in local development and is disabled/unpublished in
  dev/prod. The generated config is read-only; the UI is not a configuration authority.
- Metrics (`15020`) are scraped internally by Prometheus; readiness (`15021`) is internal.
- Upstream provider and remote MCP credentials exist only in agentgateway's environment.
- `config.database` is omitted in v1, disabling agentgateway's request-log database and avoiding
  a second audit store. Raw prompt/completion capture stays off. Metrics and redacted OTLP spans
  flow to the existing observability backend; JSONL remains authoritative.
- Network policy denies direct app egress to LLM and remote MCP endpoints where the deployment
  platform can enforce it.

## Options considered

1. **Hybrid sidecar + application policy (chosen).** Uses agentgateway for the data plane and
   preserves Smokejumper's domain-specific approval/audit invariants.
2. Replace FastMCP/application governance with agentgateway entirely. Rejected: CEL can filter
   tools but does not own LangGraph suspend/resume, Slack decisions, token consumption, B8, or
   deterministic replay.
3. Use agentgateway for LLM traffic only. Rejected: leaves remote MCP credentials, federation,
   and observability in custom application code.
4. Keep the original in-process-only design. Rejected by the explicit requirement for a gateway
   proxy and because it duplicates mature routing/transport capability.

## Trade-offs accepted

- The default stack grows from three services to four, and agentgateway becomes a critical path
  for all model and MCP calls. Health checks, timeouts, and an explicit `needs_human` degradation
  path are mandatory.
- The proxy concentrates provider/MCP credentials and sees sensitive traffic. Mitigations:
  internal listeners, least-privilege backend credentials, no raw request DB, no prompt capture,
  redacted traces, read-only generated config, and exact version/image pinning.
- Two enforcement layers can drift. The manifest generator + CI equality check makes one file
  authoritative instead of asking humans to maintain two policies.
- The admin UI can overwrite configuration. Smokejumper treats it as a local inspection surface
  only; changes are made in the manifest/descriptors and regenerated.
- Provider-specific behavior may differ behind one virtual API. Contract tests run each enabled
  provider/model role before it can be selected in an environment.

## Revisit when

- agentgateway cannot proxy a required provider/MCP protocol without semantic loss;
- proxy unavailability dominates incident investigations despite bounded retry/degradation;
- a fleet deployment needs a Kubernetes Gateway API control plane;
- a stable post-1.3 release materially changes config or MCP authorization semantics.

## Sources

- Project/repository: <https://github.com/agentgateway/agentgateway>
- Standalone configuration: <https://agentgateway.dev/docs/standalone/latest/configuration/overview/>
- Virtual MCP: <https://agentgateway.dev/docs/standalone/latest/mcp/connect/virtual/>
- MCP authorization: <https://agentgateway.dev/docs/standalone/latest/configuration/security/mcp-authz/>
- Virtual models: <https://agentgateway.dev/docs/standalone/latest/llm/virtual-models/>
- LLM observability: <https://agentgateway.dev/docs/standalone/latest/llm/observability/>
- Request-log storage/disable behavior: <https://agentgateway.dev/docs/standalone/latest/integrations/observability/database/>
