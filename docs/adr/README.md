# Architecture Decision Records

One record per significant decision, with the options considered, the trade-off we
knowingly accepted, and the condition that should reopen it. Format: lightweight MADR.
Levels: **L1** = container architecture (blocks & boundaries), **L2** = component/library
design inside a block.

| # | Level | Decision |
|---|---|---|
| [0015](0015-agent-framework-langgraph.md) | L1 | Intelligence framework: LangGraph over CrewAI / AutoGen / PydanticAI / plain code |
| [0001](0001-langgraph-not-temporal.md) | L1 | LangGraph checkpointing for durability; Temporal deferred |
| [0002](0002-one-postgres.md) | L1 | One Postgres 16 + pgvector for all state |
| [0003](0003-deterministic-edges.md) | L1 | No LLM in Receiver or Actions; B6 determinism boundary |
| [0004](0004-hexagonal-ports.md) | L1 | Hexagonal ports with loud v1 stubs |
| [0005](0005-privileged-tier-empty.md) | L1 | Privileged tool tier ships empty; approval machinery built anyway |
| [0006](0006-redis-streams-direct.md) | L2 | redis-py Streams directly; no task-queue framework |
| [0007](0007-model-provider-config.md) | L2 | Provider-agnostic LLM via init_chat_model config |
| [0008](0008-slack-socket-mode-channel-port.md) | L2 | Slack Socket Mode; ChannelAdapter port, Slack-only v1 |
| [0009](0009-handrolled-bitemporal-memory.md) | L2 | Hand-rolled bi-temporal memory behind MemoryPort; Graphiti rejected, Cognee deferred |
| [0010](0010-fastmcp-middleware-governance.md) | L2 | FastMCP middleware as governance seam, with defense-in-depth |
| [0011](0011-approvals-langgraph-interrupts.md) | L2 | Approvals on LangGraph interrupts + custom single-use tokens; HumanLayer rejected |
| [0012](0012-jsonl-audit-source-of-truth.md) | L2 | JSONL flight recorder as audit source of truth; observability platforms deferred |
| [0013](0013-ticketingport-adapters.md) | L2 | Hand-rolled TicketingPort; Linear via direct GraphQL |
| [0014](0014-handwritten-normalizers.md) | L2 | Hand-written alert normalizers seeded from Alerta; no platform sidecar |

A new ADR is required whenever a decision (a) crosses a boundary contract, (b) adds a
runtime dependency, or (c) trades away a capability. Supersede, don't edit: a changed
decision gets a new ADR linking back.
