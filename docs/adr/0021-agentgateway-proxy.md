# ADR-0021: agentgateway proxy — deferred to post-v1

**Status:** Deferred · proposed 2026-07-25 · deferred 2026-07-26 · **Level:** L1

This record was written as an adoption and is retained as a deferral. It amends nothing: v1 keeps
[ADR-0010](0010-fastmcp-middleware-governance.md)'s in-process governance seam and
[ADR-0017](0017-mcp-domain-single-gateway.md)'s single MCP domain exactly as those records
describe them. The evaluation below is preserved because it is reusable; the decision is not.

## Why this is deferred

1. **Its own security review did not clear it.** The commissioned review returned *"conditional
   accept; not safe as currently specified"* with eight High findings. A component that
   concentrates every provider credential and sees every prompt is the wrong place to accept open
   High findings.
2. **It duplicated decisions the app kept anyway.** The adoption text conceded that Smokejumper
   remains authoritative for semantic tiers, LangGraph interrupts, Slack approval, single-use
   token consumption, B8 audit, and deterministic replay. CEL discovery filtering was the only
   enforcement the proxy added, and it sat in front of an executor check that had to run anyway.
3. **It made M0 unbuildable.** M0 was specified to generate proxy policy from
   `mcp/manifest.yaml`, a file that does not exist until M5. The first milestone therefore
   depended on the second-to-last, which is why the build order stalled before a line of code.
4. **v1 has one provider, one process, and no remote MCP server required for acceptance.** Every
   capability the proxy sells — failover across providers, per-target backend credentials and TLS,
   a shared rate limit, multiplexing — prices a fleet. v1 is a single-tenant laptop deployment.

## Context (unchanged — this is why the idea was attractive)

The original design deliberately rejected a standalone MCP proxy to preserve a one-process app.
That choice left two needs inside Smokejumper code:

1. LLM provider credentials, protocol normalization, routing/failover, token accounting, and
   network telemetry.
2. MCP transport, backend credentials/TLS, federation/multiplexing, network authorization, and
   network telemetry.

`agentgateway/agentgateway` is an Apache-2.0 Rust HTTP/gRPC proxy for HTTP, LLM, MCP, and A2A
traffic. Its standalone mode supports virtual LLM models, MCP multiplexing, CEL authorization over
tool names/arguments, per-target backend auth, rate limits, Prometheus metrics, and OTLP traces.

A local source/runtime spike pinned v1.3.1 (`dbaaf7ed73671e7aec9195e35e7f726c0b14b84a`):

- release binary SHA-256 matched
  `d3b507d31a2197a2deecdaac32734af37ee5d0ecb060a06104be0086340c1e66`;
- ordinary HTTP proxy request returned 200;
- MCP initialize returned 200 with a session ID, and `tools/list` exposed 13 tools;
- an `mcpAuthorization` CEL rule reduced discovery to the single allowed `echo` tool;
- admin UI and Prometheus metrics endpoints responded; shutdown drained listeners cleanly.

That spike stands. It establishes that the product works as documented, not that Smokejumper needs
it. v1.4.0-beta.1 existed at evaluation time and was excluded; any future adoption starts from a
stable release.

## What was proposed

agentgateway v1.3.1 as a core sidecar, making the default Compose stack
`app + agentgateway + postgres + redis`. `ModelProvider` would call virtual model names
(`smokejumper-worker`, `smokejumper-synthesis`, `smokejumper-embedding`) on an internal LLM
listener. The app's single MCP client would call one virtual MCP endpoint multiplexing app-internal
FastMCP targets and remote servers, with target-prefixed tool names. A deterministic generator
would emit `compose/agentgateway/config.generated.yaml` and CEL allow rules from
`mcp/manifest.yaml`, with CI failing on drift. Provider and remote-MCP credentials would live only
in the sidecar; `config.database` and raw prompt capture would stay disabled so JSONL remained the
audit source of truth.

## What v1 does instead

- `ModelProvider` (`ports/model.py`) calls the provider SDK directly; provider and model per role
  are config, per [ADR-0007](0007-model-provider-config.md).
- FastMCP servers run in the app process, and the one MCP client reaches them over FastMCP's
  in-memory transport. Federated servers are reached over HTTPS from that same client.
- `mcp/manifest.yaml` is read at runtime by the middleware and by the executor. Nothing is
  generated, so nothing can drift.
- Default Compose is three services: postgres+pgvector, redis, app.

## Options considered

1. Hybrid sidecar + application policy. The proposed option; deferred for the four reasons above.
2. Replace FastMCP/application governance with agentgateway entirely. Rejected: CEL can filter
   tools but does not own LangGraph suspend/resume, Slack decisions, token consumption, B8, or
   deterministic replay.
3. Use agentgateway for LLM traffic only. Rejected: buys provider failover that the v1
   configuration does not ask for, while still adding a critical-path service.
4. **Keep the in-process design (chosen for v1).** One process, one manifest, two enforcement
   points, three services. The capability given up is real but unrequested at v1 scale.

## Adopt this when — falsifiable triggers

Each trigger names an observable condition. If none has fired, the in-process path is cheaper and
this record stays deferred. "We should have a gateway" is not a trigger.

1. **Provider failover becomes a requirement, with evidence.** At least one recorded run reached
   `needs_human` solely because a single provider was unavailable, and that outcome was judged
   unacceptable. Until then the circuit breaker in SPEC §5.7 is the accepted behavior.
2. **Federation crosses two auth schemes or needs mTLS.** Two or more federated MCP servers with
   different credential models, or one requiring client certificates — at which point per-target
   credential and TLS handling stops being a few lines in `mcp/federated/loader.py`.
3. **Smokejumper runs as more than one process.** Any horizontal scaling or a second replica,
   because a per-process rate limiter and a per-process credential resolver stop being correct.
4. **Multi-tenancy or per-caller tool scoping lands.** Both are v1 non-goals; a manifest that maps
   tool → tier cannot express tool → tier → caller, and CEL can.
5. **The security review's findings are closed upstream.** All eight High findings have named
   fixes in a released non-beta version, *and* a compatibility test proves config load, LLM
   routing, MCP session, tool authorization, and telemetry on that pinned version and digest.

Triggers 1–4 establish need; trigger 5 is a precondition on adoption regardless of need.

## Trade-offs of deferring

- **We gave up** provider failover, an outer token rate limit, per-target backend TLS/credential
  handling, and network-level tool authorization. The app owns rate limiting and spend control
  itself (SPEC §5.7), which it already did.
- **We gave up** a ready-made answer for the fleet deployment story. Trigger 3 is where it
  returns.
- **We kept** a three-service stack, a single enforcement path an auditor can read end to end, and
  an M0 that can actually be built.
- **We avoided** concentrating every provider credential and every prompt in a component whose own
  review says it is not yet safe as specified.

## Sources

- Project/repository: <https://github.com/agentgateway/agentgateway>
- Standalone configuration: <https://agentgateway.dev/docs/standalone/latest/configuration/overview/>
- Virtual MCP: <https://agentgateway.dev/docs/standalone/latest/mcp/connect/virtual/>
- MCP authorization: <https://agentgateway.dev/docs/standalone/latest/configuration/security/mcp-authz/>
- Virtual models: <https://agentgateway.dev/docs/standalone/latest/llm/virtual-models/>
- LLM observability: <https://agentgateway.dev/docs/standalone/latest/llm/observability/>
- Request-log storage/disable behavior: <https://agentgateway.dev/docs/standalone/latest/integrations/observability/database/>
