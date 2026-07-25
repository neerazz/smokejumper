# Smokejumper — v1 Build Specification

> Level-2 design: everything an implementer (human or agent) needs to build v1 without
> re-asking architectural questions. The level-1 container view lives in
> [architecture/](architecture/README.md) — this document refines it into contracts,
> component behavior, flows, data, and verifiable milestones.
>
> **Status: reviewed 2026-07-10; architecture updated 2026-07-25** — the five open decisions
> were resolved by Neeraj (see §10); no unresolved `⚑` remain. The 2026-07-25 pass added the
> local observability stack (§2c), per-environment configuration (§2d), and consolidated MCP
> into one domain (§5.5) — decisions 11–13. Every significant decision is recorded with its
> alternatives and accepted trade-offs in [docs/adr/](docs/adr/README.md).

## 1. Purpose & scope

**One sentence:** an alert lands, Smokejumper parachutes in, investigates in parallel with
budgeted specialist agents, and reports a grounded conclusion with receipts — creating or
updating exactly one ticket per incident fingerprint.

**v1 definition of done.** A single-tenant deployment (docker-compose) that:

1. Ingests Grafana/Datadog/PagerDuty/generic webhooks and Slack @mentions (B1), normalizes
   to `AgentEvent` (B2), dedupes and coalesces storms.
2. Runs a LangGraph supervisor that dispatches ≥3 specialist sub-agents in parallel (B11),
   retrieves knowledge (B3), and synthesizes a `Conclusion` (B6).
3. Executes deterministic actions: idempotent Linear ticket create-vs-update + Slack receipt.
4. Gates privileged tools behind a Slack approve/deny round-trip with single-use tokens (B5).
5. Records every event, LLM call, tool call, gate, and action in the Flight Recorder (B8),
   replayable through the eval harness.
6. Enforces budgets: per-run iteration/token caps, per-agent tool budgets, storm brake.

**Non-goals for v1** (explicitly deferred): multi-tenancy, real auth (stubs only), Temporal
durability (LangGraph checkpointing only), auto-applied remediations (privileged tier exists
but ships with zero privileged tools enabled), Distiller automation (manual CLI run),
horizontal scaling, UI beyond Slack.

## 2. Tech stack (locked)

| Concern | Choice | Rationale (2026-07-10 research) |
|---|---|---|
| Language | Python 3.12+ | ecosystem; team lane |
| API/webhooks | FastAPI + uvicorn | standard, async |
| Agent runtime | LangGraph + `langgraph-checkpoint-postgres` 3.x (**must set `LANGGRAPH_STRICT_MSGPACK=true`** — CVE-2026-28277 deserialization hardening). Supervisor topology is **copied as a pattern** (tool-calling supervisor per LangChain's guide), NOT a dependency on `langgraph-supervisor` — its maintainers steer users away from it | durability via Postgres checkpointer is enough for v1; Temporal deferred |
| MCP layer | FastMCP 3.x (Apache-2.0, **version-pinned**) for client + own servers + governance middleware; `langchain-mcp-adapters` loads MCP tools into LangGraph. Official `mcp` SDK v2 is beta — do not build on it yet | verified 2026-07-10; see §2b |
| Queue | Redis Streams (consumer groups) | burst absorption, replayable inbox |
| Store | **One Postgres 16** + pgvector | unified store consensus: vectors + graph edges + recorder in one DB; no separate graph DB |
| Knowledge graph | Postgres edge tables, bi-temporal (valid_at / recorded_at, Graphiti-style) | facts change; never lose what we believed at decision time |
| Memory extraction | LangMem-style extraction in Distiller; **distill, don't append** | append-everything degrades retrieval |
| LLM | **Swappable by config, zero code**: `ModelProvider` port over LangChain `init_chat_model` provider strings (`anthropic:*`, `openai:*`, `google_genai:*`, `ollama:*`, …), configured **per role** (`worker`, `synthesis`) in `config.yaml`/env. Ships with Anthropic defaults (claude-sonnet-5 workers, claude-opus-4-8 synthesis); switching to Codex/GPT, Gemini, or a local model is an edit to two config lines | hard requirement: any provider, swappable at any time; no provider import outside `ports/model.py` |
| Packaging | `uv` + `pyproject.toml`, src layout, package name `smokejumper` | PyPI name is free |
| Quality gates | ruff + pyright + pytest; CI = GitHub Actions | |

## 2b. OSS reuse map (build-vs-buy, deep-researched & source-verified 2026-07-10)

Governing rule: **never hand-write what a maintained library already does; never let a
third-party library be the sole owner of a security boundary or the audit record.**
Full evidence trail: `research_smokejumper-oss-reuse` (journal, 2026-07-10) — 4 research
lanes + adversarial verification (13/13 claims verified at primary sources).

| Component | ADOPT | HAND-WRITE (verified: no OSS covers it) |
|---|---|---|
| Slack channel | `slack-bolt` (MIT, Socket Mode first-class) | handlers only |
| Telegram channel (post-v1) | `aiogram` (MIT, async) — chosen over python-telegram-bot (LGPL) | adapter glue |
| Email channel (post-v1) | `imap-tools`/`IMAPClient` (IDLE) + `aiosmtplib` | OAuth2 token handling |
| Alert intake | — none exists: no pip-installable Grafana/Datadog/PagerDuty normalizer; Grafana OnCall archived 2026; Keep is a platform (MIT core), not a library | per-source normalizers (**seed from Alerta's Apache-2.0 `alerta/webhooks/` parsers**) + per-source HMAC verification |
| Queue | `redis-py` Streams + consumer groups (sufficient; taskiq only if we later want retry/DI abstractions; arq/celery/streaq rejected) | fingerprint dedupe window |
| Loop guards | LangChain v1 `ModelCallLimitMiddleware` + `ToolCallLimitMiddleware` (call-count caps) | token/$ spend ledger + RPM/TPM throttle (no OSS equivalent in Python) |
| Memory/GraphRAG | — Graphiti rejected (Neo4j/FalkorDB only — violates one-Postgres). Cognee 1.x verified to run GraphRAG on one Postgres with opt-in bi-temporal, but red-team verdict: don't adopt at HEAD for an audit-critical tool | bi-temporal edge tables on Postgres+pgvector using **Graphiti's data model as blueprint**, behind a `MemoryPort` (Cognee/LightRAG become optional adapters after a pinned-version spike) |
| MCP governance | FastMCP middleware `on_call_tool` hook (block via ToolError) — the embeddable tiering seam | tool→tier registry + policy middleware + **redundant enforcement in our tool executor** (security boundary never single-sourced in a third-party hook) |
| Approvals | LangGraph `interrupt()` + PostgresSaver (durable suspend/resume); slack-bolt Block Kit. **HumanLayer rejected — repo self-declares deprecated** | single-use approval tokens, 30-min expiry, token→(thread_id, tool_call) binding |
| Audit/replay | LangGraph time-travel (`get_state_history`, fork) as replay backbone | JSONL recorder (source of truth) + model-response recording for deterministic replay |
| Eval | `openevals` (MIT) or `deepeval` (Apache-2.0, pytest-native) | golden cases |
| Observability UI | **deferred to v2** (Opik = cleanest license; Langfuse = 6 services incl. ClickHouse; Phoenix = ELv2). Optional now: OpenLLMetry library-only OTel spans | — |
| Ticketing SDKs | `githubkit` (MIT, async — over PyGithub: LGPL + "seeking maintainers") · `atlassian-python-api` · official `asana` | TicketingPort (verified: no OSS unifier covers Linear+GitHub+Jira+Asana — ticketutil has the wrong provider set) + **Linear adapter via direct GraphQL** (no official Python SDK; community `linear-api` stale) |

## 2c. Local observability stack (`local` environment only, via compose profiles)

v1 must be verifiable on a laptop, so the alert sources and tool backends the system talks to
in production need runnable local equivalents. **Not all of them can have one:** Datadog and
PagerDuty are SaaS — there is no local Datadog, and having their cloud webhook back to a
laptop would need a public tunnel. Those two are exercised by **replaying recorded payloads**
at the Receiver, which is precisely what the normalizers and per-source HMAC verification
need tested anyway.

| Purpose | Service | Profile | Notes |
|---|---|---|---|
| Core runtime | postgres+pgvector · redis · app | *(default)* | `docker compose up` — one-command onboarding unchanged |
| Alert source | prometheus + alertmanager | `lab` | Alertmanager sends no HMAC ⇒ network allowlist (§5.1) |
| Alert source + dashboards | grafana (OSS) | `lab` | Grafana alerting → Receiver webhook; fully local |
| Log backend | loki + promtail | `lab` | **chosen over ELK**: ~200MB vs 4GB+ heap; Grafana-native |
| Fault injection | faultbox | `lab` | sample app that leaks / 500s / stalls on command |
| SaaS stand-in | replayer | `fixtures` | POSTs recorded Datadog/PagerDuty payloads at the Receiver |

These services fill **two distinct roles**, and the distinction is load-bearing:

1. **Alert sources** fire webhooks at the Receiver (§5.1) — Grafana alerting, Alertmanager.
2. **Tool backends** answer read-tier tool calls (§5.5): `metric query` → Prometheus,
   `log search` → Loki. Both tools were previously named with **no backend behind them**;
   this section is what makes specialist investigation real instead of stubbed.

Compose profiles keep the default `docker compose up` at three services — ADR-0002 banks
"a docker-compose a newcomer can run in one command" as a benefit, and a 10-service default
would quietly spend it. Full `lab` profile lands near 1.2GB resident.

These services are **local only**. The same tools point at dev/prod backends via environment
config (§2d), and the `lab`/`fixtures` profiles are refused outside `SMOKEJUMPER_ENV=local`.

**Why this is more than dev convenience:** a faultbox-injected incident has *known ground
truth*, so a run's Conclusion can be scored automatically rather than eyeballed. The lab is
the eval-corpus factory for §8, not a nicety. Note this is unrelated to decision §10.10
(LLM-trace observability platforms deferred to v2) — that concerns *our* audit record; this
concerns *the systems Smokejumper observes*.

## 2d. Configuration & environments (local · dev · prod)

**Naming discipline first**, because two different things want the word "profile":

- **Compose profiles** (`lab`, `fixtures` — §2c) select which *services start*.
- **Environments** (`local`, `dev`, `prod`) select which *values the app uses*.

They are orthogonal and combine freely: `SMOKEJUMPER_ENV=local docker compose --profile lab up`
is the normal local setup. This spec never calls an environment a "profile".

### Layering
One typed settings object (pydantic-settings), assembled lowest → highest precedence:

1. code defaults
2. `config/base.yaml` — env-independent defaults; no endpoints, no secrets
3. `config/<env>.yaml` — per-environment endpoints and tuning
4. environment variables — `SMOKEJUMPER__<SECTION>__<KEY>` (double underscore = nesting)
5. explicit CLI flags

`SMOKEJUMPER_ENV` selects step 3 and defaults to `local`. Boot assembles and validates the
whole object and **fails fast** on anything missing or malformed — no `os.getenv` scattered
through the codebase, and no lazily-discovered misconfiguration surfacing at minute nine of
an incident.

**Secrets never live in YAML.** Config files hold *references*; values arrive as env vars.
Local reads them from `.env` (git-ignored; `.env.example` committed). dev/prod get them
injected by the platform's secret manager. `config/` stays diffable and safe to commit.

### What varies by environment

| Concern | local | dev | prod |
|---|---|---|---|
| Postgres / Redis | compose service names | managed instance | managed instance |
| `metric query` backend | `http://prometheus:9090` (`lab`) | dev Prometheus | prod Prometheus |
| `log search` backend | `http://loki:3100` (`lab`) | dev Loki | prod Loki |
| Alert sources | `lab` + `fixtures` replay | real webhooks, dev secrets | real webhooks, prod secrets |
| Model roles (§2) | cheap or local model | cheap model | full-strength |
| Spend ceiling | tiny | tiny | real, with kill switch |
| Ticketing (§5.6) | dry-run / fixture | test Linear team | prod Linear team |
| Slack | dev workspace | dev workspace | real workspace |
| Federated MCP (§5.5) | stub descriptor | dev endpoint | prod endpoint |
| Ports (§5.10) | stubs allowed | stubs warn | **stubs forbidden** |

### Environment-gated safety rules (enforced at boot, not documented-and-hoped)
- **`prod` refuses to start if any port is a stub** (`AllowAll`, `NoopGovernance`,
  `FixturePlatform`). ADR-0004 accepted the risk that "stubs normalize insecurity if deployed
  carelessly" and mitigated it with a loud log line — a log line is not a control. Fail closed.
- **`lab` and `fixtures` compose profiles are refused outside `local`.** The faultbox exists
  to break things; it must not be reachable from a real environment.
- **`prod` requires an explicit spend ceiling.** Absent one, boot fails rather than defaulting
  to unlimited.

### How compose picks it up
`docker-compose.yml` interpolates `${VAR}` from `.env` and passes `SMOKEJUMPER_ENV` through to
the app; `docker-compose.override.yml` is auto-loaded for local convenience and git-ignored.
dev/prod use explicit overlays:

```bash
SMOKEJUMPER_ENV=local docker compose --profile lab up
SMOKEJUMPER_ENV=dev   docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Compose is a local/dev tool here. If prod runs on anything else (k8s, ECS, a single VM), the
entire contract is `config/prod.yaml` plus injected env vars — no compose file involved. That
is the point of keeping environment selection in the settings object rather than in compose.

## 2e. Observability & prompt management

### Observability — `obs` compose profile (ADR-0019)
Two layers, deliberately separated so the backend is never load-bearing:

1. **Instrumentation is OpenTelemetry** (OpenInference semantic conventions), emitted from
   inside `ports/model.py` and the MCP gateway — the two places every model call and tool call
   already funnel through. No instrumentation code in callers.
2. **The backend is a config value.** Default: **Arize Phoenix**, a single container behind the
   `obs` profile. **Langfuse** is a supported swap — repoint the OTLP exporter, change no code.

```bash
docker compose --profile obs up      # + phoenix, OTLP on 4317, UI on 6006
```

**JSONL stays the audit source of truth** (ADR-0012). The platform is a *read-side consumer*:
it can be absent, wiped, or replaced with no effect on the audit record or on replay. Nothing
in the system may depend on a trace being queryable.

Why Phoenix rather than the richer Langfuse: single process vs six services including
ClickHouse (§2c's footprint argument again), and Phoenix is **eval-first** — its faithfulness,
hallucination, and retrieval-relevance evaluators sit directly on §8's open question of
whether a Conclusion was actually grounded. The cost is licensing: Phoenix is **Elastic
License 2.0 — source-available, not OSI open source**. Do not describe it as open source; an
adopter whose procurement requires OSI licenses uses the Langfuse swap, which is exactly what
the OTel seam exists to make cheap. **LangSmith was rejected outright** — proprietary, no
practical self-host, and it would ship production log content to a third-party cloud.

### Prompt management — `prompts/` in git (ADR-0020)
Prompts are behavior, so they are versioned artifacts, not configuration strings:

```
prompts/
├── supervisor/{plan,synthesize}/v<N>.md
├── agents/<agent-name>/v<N>.md
└── CHANGELOG.md
```

The Agent Registry (§5.3) **references** rather than inlines: `prompt: agents/metrics-analyst@v3`.
Three rules make this load-bearing:

- **Versions are immutable.** Never edit `v3`; add `v4`. Same discipline as ADRs.
- **B8 records `prompt_ref` + `prompt_sha256` on every `llm_call`** (§4). Without this a
  recorded run cannot be attributed to a prompt version, a regression cannot be traced to a
  prompt change, and replay cannot assert it is running the prompt it recorded.
- **A prompt change requires an eval run** before merge — the only regression gate that exists
  for behavior.

A platform prompt playground may be used for experimentation. It is never the store and never
serves prompts at runtime: putting behavior-defining artifacts in a third-party database is
the same mistake ADR-0012 refused for the audit log.

## 3. Repository layout

```
smokejumper/
├── pyproject.toml
├── docker-compose.yml          # default: postgres+pgvector, redis, app
│                               # profiles: lab (§2c), fixtures (§2c)
├── docker-compose.override.yml  # auto-loaded local tweaks — git-ignored
├── docker-compose.dev.yml      # explicit overlay: -f base -f dev
├── .env.example                # local secret template (real .env is git-ignored)
├── config/                     # environment values (§2d) — secrets by reference only
│   ├── base.yaml               #   env-independent defaults
│   ├── local.yaml              #   compose service names, stubs allowed
│   ├── dev.yaml                #   dev endpoints, cheap models, tiny ceiling
│   └── prod.yaml               #   real endpoints; stubs forbidden at boot
├── compose/                    # provisioning for the lab profile — config, not code
│   ├── prometheus/             # scrape config + alert rules that fire at the Receiver
│   ├── alertmanager/           # webhook receiver config
│   ├── grafana/                # provisioned datasources + alert rules
│   ├── loki/                   # log store config
│   └── faultbox/               # injectable-fault sample app
├── src/smokejumper/
│   ├── contracts/              # B1–B11 pydantic models — THE source of truth
│   ├── receiver/               # FastAPI app: webhook routes, verify port, normalize, dedupe
│   ├── queue/                  # Redis Streams producer/consumer
│   ├── intelligence/           # LangGraph graph, supervisor, registry loader, sub-agent runner
│   ├── knowledge/              # facade, vector store, graph store, recipes (federates via mcp/)
│   ├── mcp/                    # THE MCP domain — one client, one governance seam (§5.5)
│   │   ├── gateway.py          #   single FastMCP client + governance middleware
│   │   ├── tiers.py            #   tier enforcement + redundant executor check
│   │   ├── approvals.py        #   approval broker (B5 token lifecycle)
│   │   ├── manifest.yaml       #   SINGLE tool→tier registry — ours AND federated
│   │   ├── servers/            #   servers we implement, in-process
│   │   │   ├── metrics/        #     → Prometheus
│   │   │   ├── logs/           #     → Loki
│   │   │   ├── knowledge/      #     → knowledge.search / knowledge.expand
│   │   │   └── testing/        #     → demo_destructive_noop (ADR-0005)
│   │   └── federated/          #   external servers we consume, never run
│   │       ├── loader.py       #     imports remote toolsets through the same gateway
│   │       └── descriptors/    #     curlix.yaml, … — config, not code
│   ├── actions/                # deterministic executors: linear, slack receipts, findings
│   ├── recorder/               # flight recorder writer + replay/eval harness
│   ├── governor/               # budgets, circuit breakers, storm brake, scheduler
│   ├── distiller/              # CLI: recorder → embeddings/edges/draft recipes
│   └── ports/                  # auth/governance/tenancy/model interfaces + v1 stubs
├── registry/agents/*.yaml      # declarative specialist definitions (reference prompts)
├── prompts/                    # prompt registry (§2e) — immutable versions, git is SoT
│   ├── supervisor/             #   plan/vN.md, synthesize/vN.md
│   ├── agents/                 #   <agent-name>/vN.md
│   └── CHANGELOG.md
├── recipes/*.yaml              # runbook recipes (procedural memory)
├── fixtures/webhooks/          # golden per-source payloads (§8) + replayer corpus (§2c)
├── tests/                      # unit + contract + replay tests
└── evals/                      # recorded cases for the replay harness
```

Dependency rule: `contracts` imports nothing internal; everything imports `contracts`;
`intelligence` never imports `actions` (only emits B6); `actions` never imports an LLM client.
**`mcp` is the only package that speaks MCP** — no other package constructs an MCP client, so
every tool call (ours or federated) crosses exactly one governance seam; `knowledge`
federates by calling `mcp`, never by opening its own connection.

## 4. Boundary contracts (B1–B11)

All contracts are pydantic models in `src/smokejumper/contracts/`, versioned with a
`schema_version` field. Breaking changes bump the version; the recorder stores the version
with every payload.

- **B1 · VerifiedInbound** — transport-level: raw body + headers, passed only after the Auth
  port validates the source signature (Grafana/DD/PD secret, Slack signing). Stub: AllowAll.
- **B2 · AgentEvent** — the single input type intelligence accepts:
  `{id, schema_version, source(grafana|datadog|pagerduty|generic|slack|scheduled), kind(alert|chat|scheduled), fingerprint, severity(critical|high|medium|low|info), title, body, entities[{type,id}], occurred_at, received_at, dedupe_count, raw}`.
  Fingerprint = stable hash of (source, alertname/monitor-id, entity set) — NOT of the text.
- **B3 · retrieve(ctx) → KnowledgeBundle** — `{episodes[], graph_paths[], recipes[], federated[], tokens_used}`; every item carries `{content, source_ref, valid_at, recorded_at, score}`.
- **B4 · ToolCall / ToolResult** — `{run_id, agent, tool, args, tier(read|privileged)}` →
  `{ok, value|error, latency_ms, cost}`. Read tier executes; privileged tier suspends the run.
- **B5 · ApprovalRequest / ApprovalDecision** — request: `{id, run_id, tool_call, reason, requested_at, expires_at(30m)}`; decision: `{approved, decided_by, decided_at, token}` where token is single-use, minted by the Auth port, and consumed on execution. Expiry ⇒ auto-deny.
- **B6 · Conclusion** — the determinism boundary:
  `{run_id, fingerprint, status(root_caused|mitigated|inconclusive|needs_human), confidence(0-1), summary_md, findings[], evidence_refs[], proposed_actions[], tokens_spent, wall_ms}`.
  Nothing downstream of B6 may call a model.
- **B8 · AuditEvent** — `{run_id, seq, ts, actor(block or agent), kind(event|transition|llm_call|tool_call|gate|action), payload, schema_version}`; append-only, async, every block emits.
  `llm_call` events additionally carry `{prompt_ref, prompt_sha256, model}` (§2e) so a run is
  attributable to an exact prompt version and replay can assert prompt identity.
- **B9 · DistillationCandidate** — a closed case bundle from the recorder → Distiller.
- **B10 · PlatformPort** — external host-platform API (e.g. Curlix): `skills.execute`,
  `assets.query`, `findings.write`. v1 stub: no-op + fixture data.
- **B11 · Assignment / Finding** — assignment: `{agent, question, context_slice, budget{tool_calls, tokens}}`; finding: `{agent, hypothesis, evidence[], confidence, budget_spent}`.

(B7 is intentionally unassigned — reserved, keeps historical numbering from the diagram.)

## 5. Component specifications

### 5.1 Receiver — deterministic, no LLM, no writes
- All inbound surfaces implement a **`ChannelAdapter` port** (`listen()` → yields raw
  inbound, `send(receipt)`); **v1 ships exactly one chat adapter: Slack.** Telegram
  (`aiogram`) and email (`imap-tools`/`IMAPClient`) are documented adapter stubs behind
  the same port — designed for, not built (red-team: building them in v1 is scope creep).
- Per-source alert normalizers are hand-written (verified: no OSS library does this),
  **seeded from Alerta's Apache-2.0 `alerta/webhooks/` parsers** (grafana, prometheus,
  pagerduty, cloudwatch, …) with attribution. Signature verification is per-source HMAC,
  also hand-written (Alertmanager sends none — allowlist by network instead).
- One FastAPI route per alert source (Grafana/Datadog/PagerDuty/generic). **Slack runs in
  Socket Mode via `slack-bolt`** (a listener task next to FastAPI — no public URL needed;
  inbound events and outbound Web API calls use the same bot). Requires a Slack app Neeraj
  creates once: bot token (`xoxb-`) + app token (`xapp-`, `connections:write`), bot scopes
  `app_mentions:read`, `chat:write`, `channels:history`, `reactions:write` + interactivity
  enabled for the approve/deny buttons.
- Verify via Auth port (B1) → normalize to AgentEvent (B2) → fingerprint → dedupe window (default 15 min: same fingerprint increments
  `dedupe_count` on the open event instead of emitting a new one) → coalesce storms (>20
  distinct fingerprints from one source in 5 min ⇒ emit ONE `storm` AgentEvent that wraps the
  set; per-alert events are recorded but not enqueued).
- Failure mode: unverifiable payload → 401 + recorder entry; unparseable → quarantine table + 202.

### 5.2 Queue — Redis Streams
- Stream `agentevents`, consumer group `intelligence`. At-least-once; consumers idempotent by
  `event.id`. Backpressure = Governor sets max in-flight runs (default 3).

### 5.3 Intelligence — LangGraph
- **Supervisor graph nodes:** `intake → retrieve(B3) → plan → dispatch(B11, parallel) →
  aggregate → synthesize(B6)`, with `approval_wait` as an interrupt node.
- **Checkpointing:** LangGraph Postgres checkpointer; a run survives process restart; an
  approval interrupt persists until decision/expiry.
- **Agent Registry:** YAML per specialist: `{name, version, prompt_ref, tools[] (allowlist),
  budget{max_tool_calls: 8, max_tokens: 50k}, dispatch{triggers}}`. `prompt_ref` points into the
  prompt registry (§2e) — e.g. `agents/metrics-analyst@v3` — so prompt text is never inlined
  here and a behavior change is never buried in a config diff. Loaded at boot; hot-reload on
  Governor's registry-sync tick. Adding an agent is config, not code.
- **v1 specialists (3):** Metrics Analyst, Log Analyst, Change
  Auditor. (DB Investigator, Code Investigator, Precedent Researcher are registry entries
  marked `enabled: false` with prompts stubbed.)
- Sub-agents are stateless: input = Assignment, output = Finding; no memory between runs.

### 5.4 Knowledge
- Façade: `retrieve(ctx: AgentEvent | str, budget) → KnowledgeBundle`. GraphRAG: pgvector
  similarity finds entry nodes → graph expansion (≤2 hops) over edges
  `caused_by | fixed_by | applies_to` → recipes matched by trigger tags → federated sources
  queried only if local results < threshold. **Federation goes through the shared MCP gateway**
  (§5.5) and is tiered like any other tool call — the façade does not own an MCP client, so
  modality ④ cannot become a second, ungoverned path to an external server.
- Bi-temporal: every node/edge has `valid_at` + `recorded_at`; retrieval defaults to
  "currently valid" but replay can query "as believed at time T".
- **Implementation stance (researched):** the store is hand-rolled Postgres tables using
  **Graphiti's bi-temporal data model as the blueprint** (entity/edge with
  valid_at/invalid_at + created_at/expired_at; pgvector embeddings) — Graphiti itself is
  rejected (requires Neo4j/FalkorDB; violates one-Postgres). Everything sits behind a
  `MemoryPort`, so Cognee (verified: single-Postgres GraphRAG, opt-in temporal mode) or
  LightRAG can replace the hand-rolled store later via a pinned-version spike without
  touching callers.

### 5.5 MCP domain — one gateway, one manifest
All MCP concerns live in `src/smokejumper/mcp/` (§3). It replaces the former `hub/` package
and absorbs the federated client that previously sat in `knowledge/`. **One client, one
governance seam, one tier registry** — see ADR-0017.

- **Single tier manifest.** `mcp/manifest.yaml` assigns every tool a tier — servers we run
  *and* federated ones. Deliberately NOT co-located with each server: a tool's tier must not
  be declarable next to the tool, or a new server can self-declare `read` on a destructive
  capability and no reviewer sees the security change. One manifest ⇒ every tier change is a
  reviewable one-file diff.
- **v1 read tools, with real backends** (previously named but unbacked):
  `metric query` → Prometheus · `log search` → Loki (both from the `lab` profile, §2c) ·
  `knowledge.search` / `knowledge.expand` → the Knowledge façade (§5.4) · `Linear read` ·
  `recipe read` · `platform asset query` (stub).
- **Privileged tier ships EMPTY.** Gating machinery (suspend → B5 → token → execute) is built
  and tested against `mcp/servers/testing/demo_destructive_noop`, enabled only in tests.
- **Our servers run in-process.** FastMCP supports standalone processes; v1 does not use them
  — in-process keeps the single-service deployment ADR-0001 treats as decisive. Compose gains
  services for the *backends* (Prometheus, Loki), never for our servers.
- **Federation is consumption, not implementation.** `mcp/federated/descriptors/*.yaml`
  declare external servers (endpoint, auth, tool allowlist); `loader.py` imports their
  toolsets through the same gateway and the same manifest. Descriptors are config, not code.
- **Implementation stance (researched):** built on FastMCP 3.x (pinned) — its
  `on_call_tool(context, call_next)` middleware reads the tier registry and blocks/gates by
  raising `ToolError`; `langchain-mcp-adapters` exposes the governed toolset to LangGraph.
  Dedicated MCP gateways (IBM ContextForge, Lasso, mcp-guardian) were evaluated and rejected
  for v1 — all are standalone proxy services, not embeddable libraries. **Defense in depth:**
  tier enforcement is duplicated in our tool executor so the security boundary never lives
  solely in third-party middleware.

### 5.6 Actions — deterministic, no LLM
- Input: Conclusion (B6). Fingerprint rules: open ticket exists for fingerprint ⇒ update
  (comment + status), else create. Idempotency key = `(fingerprint, run_id)` — retries never
  double-post. Outputs: ticket via TicketingPort, Slack receipt (thread on the alerting
  channel message when Slack-sourced), platform findings write-back (stub).
- **TicketingPort — extensible base adapter** in `ports/ticketing.py`:
  `create(TicketDraft) → TicketRef` · `update(TicketRef, TicketUpdate)` ·
  `find_open_by_fingerprint(fp) → TicketRef | None` · `close(TicketRef, resolution)`.
  `TicketDraft/Update/Ref` are provider-neutral contract models; adapters map them to the
  provider. v1 ships the **Linear** adapter; GitHub Issues, Jira, and Asana are later
  adapters behind the same interface — selected in config (`ticketing.provider: linear`).
  Adapter conformance is enforced by a shared contract-test suite every adapter must pass.

### 5.7 Governor + Scheduler
- Per-run caps: max 12 graph iterations, 200k tokens, 10 min wall clock — breach ⇒ synthesize
  `inconclusive` Conclusion with partial findings (never silent death). Call-COUNT caps reuse
  LangChain v1 `ModelCallLimitMiddleware`/`ToolCallLimitMiddleware`; the token/$ spend ledger
  (from `usage_metadata` into Postgres) and RPM/TPM throttle are hand-written — verified no
  Python OSS equivalent exists.
- Circuit breakers: 3 consecutive provider failures ⇒ pause consumption 60s. Storm brake:
  queue depth > 25 ⇒ only `critical|high` dequeued.
- Scheduler (APScheduler): registry sync, scheduled investigations from recipes, approval-expiry sweeper.

### 5.8 Flight Recorder + replay harness
- **Sink = append-only JSONL files in the log directory** (`logs/` by default,
  `SMOKEJUMPER_LOG_DIR` to override): one file per UTC day with a timestamp suffix,
  `audit-<YYYY-MM-DD>T<HHMMSS>.jsonl` (new suffix per process start, so restarts never
  interleave). One AuditEvent per line. No retention policy — files accumulate; rotation is
  the operator's business.
- **Streamable:** each event is also emitted on an in-process async broadcast channel;
  `smokejumper logs --follow` tails it, and the same channel is the seam for a future
  network stream (e.g. SSE) — write path stays file-first either way.
- Postgres keeps only a lightweight `runs` index (run_id → fingerprint, status, log file +
  byte offsets) so replay can locate a run's events without scanning every file.
- Failure to write the file sink is itself recorded to stderr and increments a health
  counter surfaced by the Governor.
- Replay harness: `smokejumper replay <run_id>` re-executes a recorded run with the model
  mocked from recorded outputs (deterministic) or live (eval mode); `smokejumper eval` runs
  `evals/*.json` cases and reports per-agent hit-rate vs recorded ground truth. Both read
  the JSONL sink via the `runs` index.

### 5.9 Distiller (manual in v1)
- `smokejumper distill <run_id|--since>`: closed cases → case embedding (①), proposed graph
  edges (②), draft recipe (③). ① and ② auto-commit; ③ writes `recipes/drafts/` — a human
  promotes drafts. One-way: Distiller writes knowledge, never reads chat.

### 5.10 Ports (hexagonal seam)
`AuthPort`, `GovernancePort`, `TenancyPort`, `ModelProvider`, `PlatformPort` — interfaces in
`ports/`, v1 stubs: `AllowAll`, `NoopGovernance`, `SingleTenant`, `EnvCredentials`,
`FixturePlatform`. Every stub logs loudly at boot that it is a stub.

**Environment gate (§2d):** stub selection is env-aware and enforced, not advisory —
`local` allows stubs, `dev` warns, and **`prod` refuses to boot** while any security-relevant
port is stubbed. A stub that only writes a log line is indistinguishable from a real port to
everything except a human reading logs, which is exactly the failure ADR-0004 flagged and did
not close.

## 6. Sequence flows (level-2)

### 6.1 Alert triage (happy path)
Grafana webhook → Receiver verifies+normalizes → dedupe miss → enqueue → supervisor intake →
retrieve (bundle: 2 similar past cases + 1 recipe) → plan selects specialists → parallel
Assignments → Findings back → aggregate → synthesize Conclusion(root_caused, 0.82) →
Actions: create Linear ticket SMOKE-123 + Slack receipt with evidence links → recorder has
the full trace → run closed.

### 6.2 Approval round-trip
Sub-agent requests privileged tool → MCP gateway suspends run (LangGraph interrupt persisted) →
ApprovalRequest → Slack message with Approve/Deny buttons → human approves → Auth port mints
single-use token → tool executes once → token consumed → run resumes. Deny or 30-min expiry ⇒
tool result = `denied`, agent must proceed without it.

### 6.3 Storm
40 fingerprints in 3 min → Receiver coalesces to one `storm` event → supervisor gets the set,
investigates the common cause once → ONE ticket, per-alert dedupe counters → storm brake keeps
queue responsive for unrelated criticals.

### 6.4 Slack Q&A
`@smokejumper why did checkout error rate spike?` → chat-kind AgentEvent → same graph, but
`plan` may answer from knowledge alone (no dispatch) → Conclusion posted as thread reply;
no ticket unless asked.

## 7. Data model (Postgres, one database)

`events` (B2, quarantine flag) · `runs` (fingerprint, status, budgets, audit-log file +
offsets — the index into the JSONL audit sink; B8 events themselves live in `logs/`, not
Postgres) · `approvals` (B5) · `tickets` (fingerprint ↔ TicketRef map, provider-tagged) ·
`kg_nodes` / `kg_edges` (bi-temporal) · `episodes` (case embeddings, pgvector) ·
`checkpoints` (LangGraph) · `schema_migrations` (alembic).

## 8. Testing & acceptance

- **Contract tests:** every B-model round-trips JSON; golden fixtures per source webhook.
- **Component tests:** dedupe/coalesce truth table; fingerprint stability; idempotent actions
  (double-delivery ⇒ one ticket); approval expiry ⇒ deny; budget breach ⇒ inconclusive.
- **Replay tests:** 5 recorded eval cases run deterministically in CI (mocked model).
- **Lab end-to-end (`lab` profile, §2c):** faultbox injects a known fault → Prometheus/Grafana
  alert fires → full run → Conclusion compared against the *injected* ground truth. This is
  how eval cases get generated instead of hand-authored, and it is the only test in the suite
  where "was the conclusion correct" is mechanically answerable. Not CI-gated (needs the lab);
  run before a release.
- **Acceptance (v1 exit):** docker-compose up + seeded fixtures; firing the three golden
  webhooks yields: 1 ticket with correct create-vs-update behavior, Slack receipt, full
  recorder trace, `smokejumper eval` ≥ 4/5 cases matching expected Conclusion status.

## 9. Milestones (each independently verifiable)

| # | Deliverable | Exit check |
|---|---|---|
| M0 | Repo skeleton, contracts, CI, docker-compose (default profile), `config/` layering (§2d), stub ports | `pytest` green; compose boots; `SMOKEJUMPER_ENV=prod` fails closed on stub ports |
| M1 | Receiver + queue + recorder core + `lab`/`fixtures` profiles (§2c) | golden webhooks → normalized events in DB, storm test passes; a real Grafana/Alertmanager alert reaches the queue |
| M2 | Supervisor + ONE specialist + Actions (ticket+receipt) | end-to-end triage of golden case #1 |
| M3 | Knowledge façade (vectors+graph+recipes) wired into retrieve | bundle appears in trace; precedent case cited |
| M4 | Parallel specialists + budgets + Governor | 3 agents in parallel; budget-breach test passes |
| M5 | MCP tiers + approval round-trip | demo noop tool gated end-to-end in test; federated descriptor loads through the same manifest |
| M6 | Replay/eval harness + Distiller CLI + `obs` profile (§2e) + docs | acceptance suite green; README quickstart works; a run's spans land in Phoenix |

Build order is strict; each milestone lands as a reviewed PR.

## 10. Decisions log (resolved 2026-07-10, by Neeraj)

1. **LLM** — provider-agnostic and swappable by config at any time (Anthropic, OpenAI/Codex,
   Gemini, local, anything). No provider code outside the ModelProvider port. Anthropic is
   only the shipped default config.
2. **v1 specialist subset** — default stands: Metrics Analyst, Log Analyst, Change Auditor
   enabled; other three registered but disabled.
3. **Slack transport** — Socket Mode (easiest two-way: Slack calls us, we call Slack, no
   public URL). Neeraj creates the Slack app; required scopes listed in §5.1.
4. **Ticketing** — extensible `TicketingPort` base from day one; Linear is the first adapter,
   GitHub Issues / Jira / Asana follow behind the same interface (§5.6).
5. **Audit log retention** — none enforced. Recorder writes dated, timestamp-suffixed JSONL
   files to the log directory, streamable via a broadcast channel; Postgres holds only the
   run index (§5.8).

Added after the OSS-reuse deep research (2026-07-10, four verified lanes + adversarial pass —
see §2b):

6. **Reuse over reinvent** — adopt the §2b libraries; hand-write only what was verified to
   have no maintained OSS equivalent (alert normalizers, approval tokens, spend ledger,
   TicketingPort, bi-temporal store).
7. **Memory** — hand-rolled bi-temporal Postgres store behind `MemoryPort`, Graphiti's data
   model as blueprint; Cognee/LightRAG adoptable later via spike. Graphiti rejected
   (separate graph DB). HumanLayer rejected (abandoned).
8. **Channels** — `ChannelAdapter` port; v1 ships Slack only; Telegram (aiogram) and email
   are designed-for, post-v1.
9. **Governance defense-in-depth** — FastMCP middleware is the seam, never the sole
   enforcement; executor re-checks tiers.
10. **Observability platforms deferred to v2** — JSONL stays the audit source of truth;
    at most library-only OTel (OpenLLMetry) in v1.

Added 2026-07-25 (architecture update):

11. **Local observability stack in compose profiles** (§2c, ADR-0016) — Prometheus+Alertmanager,
    Grafana, Loki+Promtail and a faultbox run under a `lab` profile so alert sources and tool
    backends are real locally; Datadog/PagerDuty are SaaS and get a `fixtures` replayer
    instead. Loki over ELK on footprint. Default `docker compose up` stays three services.
12. **One MCP domain** (§5.5, ADR-0017) — `hub/` and the `knowledge/` federated client
    collapse into `src/smokejumper/mcp/`: one client, one governance seam, one central tier
    manifest, our servers in-process, federated servers as descriptors. This closes a path
    where knowledge federation reached an external server without a tier check.
13. **Layered per-environment config** (§2d, ADR-0018) — `local`/`dev`/`prod` selected by
    `SMOKEJUMPER_ENV`, layered `base.yaml` → `<env>.yaml` → env vars → flags into one
    validated settings object; secrets by reference only. Deliberately distinct from compose
    profiles, which select services rather than values. Prod fails closed on stub ports and on
    a missing spend ceiling, and the `lab`/`fixtures` profiles are refused outside `local`.
14. **Observability via an OTel seam** (§2e, ADR-0019) — instrument once with
    OpenTelemetry/OpenInference inside the model port and MCP gateway; Phoenix is the default
    backend behind an `obs` profile (single container, eval-first) with Langfuse as a
    config-only swap. Amends ADR-0012's "no trace UI in v1" while keeping JSONL authoritative.
    Phoenix is ELv2 — source-available, not OSI. LangSmith rejected: proprietary + data egress.
15. **Prompts are versioned artifacts in git** (§2e, ADR-0020) — `prompts/` is the source of
    truth, versions are immutable, the registry references instead of inlining, and every
    `llm_call` records `prompt_ref` + `prompt_sha256` so regressions are attributable and
    replay can assert prompt identity. Platform prompt registries rejected as the store.
