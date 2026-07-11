# ADR-0015: Intelligence framework — LangGraph over CrewAI, AutoGen, PydanticAI, plain code

**Status:** Accepted · 2026-07-10 · **Level:** L1 (the framework shapes every L2 choice inside Intelligence)

## Context
The Intelligence block needs: a supervisor topology with parallel budgeted sub-agents,
durable suspend/resume for human approvals (up to 30 min, across restarts), replayable
state history, provider-agnostic models (ADR-0007), and MCP tool wiring. The framework
choice cascades into checkpointing, approvals, replay, and eval design.

## Decision
LangGraph (the graph runtime of the LangChain family). The supervisor is written directly
as a tool-calling graph — `langgraph-supervisor` is used as reference only. From the wider
LangChain layer we take only `init_chat_model` and the v1 call-limit middleware.

## Options considered
1. **LangGraph (chosen).** The only candidate where the three hard requirements are
   first-class *and* production-proven together: durable Postgres checkpointing,
   `interrupt()`/`Command(resume=)` human-in-the-loop that persists across restarts, and
   `get_state_history` time-travel for replay. Plus maintained MCP adapters
   (`langchain-mcp-adapters`) and the largest agent-framework ecosystem.
2. CrewAI — fastest way to stand up role-based multi-agent crews; weakest on exactly our
   spine: durable interrupt/resume and fine-grained per-agent budget control are not
   first-class; opinionated abstractions fight the deterministic B6 boundary.
3. AutoGen/AG2 — conversation-centric research lineage; Microsoft's 2025 convergence of
   AutoGen toward Semantic Kernel created roadmap churn; durability/HITL persistence not
   core primitives.
4. PydanticAI (+pydantic-graph) — the cleanest typed API and philosophically closest to our
   contracts-first design, but its graph/durability/interrupt story is young and unproven
   for suspended-for-30-minutes production runs. Strong future candidate.
5. OpenAI Agents SDK — tilts toward one provider's primitives; conflicts with ADR-0007.
6. Plain Python (no framework) — maximum control, but we would hand-write checkpointing,
   interrupts, and replay: precisely the already-invented wheel this project must not rebuild.

## What made the choice
The approval flow decided it. "Suspend a half-finished multi-agent run, survive a restart,
resume on a Slack button press, and leave a queryable audit trail" is native LangGraph
(interrupt + PostgresSaver) and DIY everywhere else. Replay/time-travel and MCP adapters
came free with the same pick; the 2026-07-10 research sweep independently landed on
"LangGraph-only durability for v1".

## Trade-offs accepted
- **We accepted** LangChain-ecosystem coupling: abstraction churn across major versions,
  a security posture we must track (e.g. CVE-2026-28277 in checkpoint deserialization —
  mitigated by the mandatory strict-msgpack flag), and pinned-version discipline.
- **We gave up** CrewAI's authoring speed and PydanticAI's cleaner typing ergonomics.
- **We contained the blast radius:** Intelligence talks to the world only through B2 in and
  B6 out, and specialists are declarative YAML. If LangGraph ever has to go, the rewrite is
  one block behind stable contracts, not the system.

## Revisit when
PydanticAI's durable-execution + HITL story reaches production maturity with a migration
win worth one block's rewrite, or LangChain-family churn breaks us twice in one year.
