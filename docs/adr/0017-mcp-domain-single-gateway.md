# ADR-0017: One MCP domain — single gateway, single tier manifest, governed federation

**Status:** Accepted · 2026-07-25 · **Level:** L2 · **Amends** [ADR-0010](0010-fastmcp-middleware-governance.md)

## Context
MCP concerns were split across two packages: `hub/` owned the tool gateway, manifest, tiers,
and approval broker, while `knowledge/` owned a separate "federated MCP client" for retrieval
modality ④. That is two MCP clients with two different governance stories.

The consequence is visible in the container diagram, which drew **two paths to Curlix**:
`READT → CURLIX` through the governed read tier, and `MODS -. federation .-> CURLIX` straight
out of the knowledge modalities. The second path never crossed the `on_call_tool` tier check.
ADR-0010's entire thesis is that tool governance gets defense in depth and that the security
boundary is never single-sourced — and there was a second door with no check on it at all.

Separately, the spec had no home for MCP servers Smokejumper *implements* (the metric, log,
and knowledge-retrieval tools all need one), and no distinction between servers we run and
servers we merely consume.

## Decision
Collapse everything MCP into one domain, `src/smokejumper/mcp/`:

- `gateway.py` — the **only** MCP client in the codebase, carrying the FastMCP governance
  middleware. Enforced by the §3 dependency rule: no other package constructs an MCP client.
- `manifest.yaml` — a **single** tool→tier registry covering our servers and federated ones.
- `tiers.py` / `approvals.py` — enforcement (plus the ADR-0010 redundant executor check) and
  the B5 token lifecycle, moved from `hub/`.
- `servers/` — servers we implement, run **in-process** and reached over FastMCP's in-memory
  transport (metrics → Prometheus, logs → Loki, knowledge → the §5.4 façade, testing →
  `demo_destructive_noop`).
- `federated/descriptors/*.yaml` — external servers declared as config, loaded through the
  same client and the same manifest.

`hub/` is deleted. `knowledge/` federates by calling `mcp`.

Putting a standalone proxy in front of this client was proposed and deferred
([ADR-0021](0021-agentgateway-proxy.md)), so the client connects to local and federated targets
itself — which is the arrangement this record describes.

## Options considered
1. **One domain under `src/`, central manifest (chosen).**
2. Top-level `mcp-servers/` directory as a peer of `src/` — matches how the servers would be
   organized if they were independently deployable, but fights the `uv` src layout (§2) for
   any server that is importable Python, and implies a process boundary v1 does not want.
3. Per-server tier declarations, co-located with each server — better locality and the
   obvious "domain-oriented" choice. **Rejected on security grounds:** if a tool's tier is
   declarable next to the tool, a new server can self-declare `read` on a destructive
   capability and no reviewer of that PR sees a security change. Tiering must be a
   one-file diff.
4. Leave federation in `knowledge/` and add a tier check there too — closes the bypass but
   institutionalizes two clients and two enforcement points that must stay in sync forever.
5. Run our MCP servers as separate compose services — real isolation, and the direction to go
   if a server ever needs its own dependency set; rejected for v1 because it breaks the
   single-service deployment ADR-0001 treats as the deciding factor.

## Trade-offs accepted
- **We gave up** locality: a contributor adding a tool edits their server directory *and* the
  central manifest. That second edit is the point — it is the security review surface.
- **We gave up** per-server dependency isolation by running in-process. A server needing a
  conflicting dependency forces the option-5 conversation.
- **We accepted** a larger `mcp/` package as the price of one governance seam, and a one-time
  refactor cost that is near zero today because no code exists yet — which is precisely why
  this lands now rather than after M5.
- **We kept** the ADR-0010 property that mattered and was quietly broken: *every* tool call,
  ours or federated, crosses exactly one governed seam with a redundant executor check behind
  it. Federation is no longer an exception.

## Revisit when
A federated server needs governance our manifest cannot express (per-caller scoping, rate
limits per remote), or an in-process server needs an isolated dependency set — the first
points at ContextForge as optional external infra (already ADR-0010's escape hatch), the
second at option 5.
