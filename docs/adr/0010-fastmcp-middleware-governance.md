# ADR-0010: FastMCP middleware as the governance seam, with defense-in-depth

**Status:** Accepted · 2026-07-10 · **Level:** L2

## Context
Every tool call must pass a tier check (read = free, privileged = approval-gated). Research
verified FastMCP 3.x middleware (`on_call_tool(context, call_next)`, block by raising
`ToolError`) is the only *embeddable in-process* Python governance hook; dedicated MCP
gateways (IBM ContextForge, Lasso, mcp-guardian) are all standalone proxy services.

## Decision
FastMCP 3.x (version-pinned) is both MCP client and our-servers runtime; a custom
middleware reads the tool→tier registry and gates privileged calls. Tier enforcement is
**duplicated in our tool executor** — the third-party hook is never the only check.

## Options considered
1. **FastMCP middleware + redundant executor check (chosen).**
2. ContextForge as a fronting proxy service — production-grade RBAC/SSO/audit, but a second
   deployed service that would fight LangGraph for ownership of suspend/resume.
3. Pure custom gateway (no FastMCP) — full control, but re-implements MCP client/server
   plumbing that FastMCP does well and keeps current with a fast-moving spec.

## Trade-offs accepted
- **We accepted** coupling the enforcement *point* to a fast-moving project (MCP spec churn,
  official SDK v2 migration mid-2026) — mitigated by pinning and by the duplicate check,
  so a semantic change in the middleware API degrades to "second check catches it".
- **We gave up** org-level governance features (SSO, multi-tenant RBAC, central registry) —
  those return via ContextForge as *optional external infra* if Smokejumper is ever deployed
  fleet-wide.
- **We kept** single-process simplicity and a governance seam that is ~30 lines of our code.

## Revisit when
FastMCP 4.x changes middleware semantics, or a deployment needs org-wide tool registry/SSO.
