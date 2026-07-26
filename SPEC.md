# Smokejumper — v1 Build Specification

> Level-2 design: everything an implementer (human or agent) needs to build v1 without
> re-asking architectural questions. The level-1 container view is the
> [component diagram](architecture/smokejumper-components.svg); this document refines it into
> contracts, component behavior, flows, data, and verifiable milestones.
>
> **Status: design complete; implementation not started. Reviewed 2026-07-10; architecture
> updated 2026-07-25; scope subtracted 2026-07-26.** The 2026-07-25 pass added the local
> incident lab (§2c), per-environment configuration (§2d), one MCP domain (§5.5), OTel/Phoenix,
> and the prompt registry — decisions 11–15. The 2026-07-26 subtraction pass removed five layers
> v1 does not need: the agentgateway proxy, the knowledge-graph tables, local Grafana, the
> `fixtures` compose service, and the Distiller (decision 17). Every significant decision is
> recorded with its alternatives and accepted trade-offs in [docs/adr/](docs/adr/README.md).

## 0. Documentation contract

This file is the **single normative source for v1**: current requirements, configuration
semantics, prerequisites, operator inputs, build order, commands, and acceptance evidence all
live here. The other repository documents have narrower jobs:

- [`README.md`](README.md) is a non-normative landing page. It may summarize the purpose and
  link here, but it must not carry its own setup commands, ports, dependency versions, config
  values, or milestone requirements.
- [`docs/adr/`](docs/adr/README.md) records *why* a decision was made and what would reopen it.
  ADRs are historical rationale, not a second current configuration manual.
- [`architecture/`](architecture/) visualizes this specification. A diagram that disagrees
  with this file is stale and must be regenerated or edited.

If two documents disagree about current behavior, **this specification wins and the follower
is fixed in the same change**. Planned commands are labelled as planned until their milestone
lands; documentation must not tell a reader to run an artifact that does not exist yet.

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
but ships with zero privileged tools enabled), the Distiller (deferred entirely — there is no v1
`distill` command, §5.9), knowledge-graph retrieval (§5.4), horizontal scaling, UI beyond Slack.

## 2. Tech stack (locked)

| Concern | Choice | Rationale (2026-07-10 research) |
|---|---|---|
| Language | Python 3.12+ | ecosystem; team lane |
| API/webhooks | FastAPI + uvicorn | standard, async |
| Agent runtime | LangGraph + `langgraph-checkpoint-postgres` 3.x (**must set `LANGGRAPH_STRICT_MSGPACK=true`** — CVE-2026-28277 deserialization hardening). Supervisor topology is **copied as a pattern** (tool-calling supervisor per LangChain's guide), NOT a dependency on `langgraph-supervisor` — its maintainers steer users away from it | durability via Postgres checkpointer is enough for v1; Temporal deferred |
| MCP layer | FastMCP 3.x (version-pinned) implements our servers and the application client/policy seam; the servers run in the app process and the one client reaches them over FastMCP's in-memory transport. `langchain-mcp-adapters` loads that governed toolset into LangGraph | one governed seam, and no network hop to reach our own tools; see ADR-0010/0017 |
| Queue | Redis Streams (consumer groups) | burst absorption, replayable inbox |
| Persistence | SQLAlchemy 2 async + psycopg 3 + Alembic over **one Postgres 16** + pgvector | application state, vectors, checkpoints, and the JSONL run/file-offset index share one DB; audit events themselves stay in JSONL |
| Knowledge | pgvector similarity over `episodes` + YAML recipes; `episodes` carries bi-temporal `valid_at`/`recorded_at` | facts change; never lose what we believed at decision time. Edge tables and graph expansion are post-v1 behind `MemoryPort` (§5.4) |
| LLM + embeddings | `ModelProvider` calls the provider SDK directly; provider and model are config per role (`worker`, `synthesis`, `embedding`) with no provider code outside the port (ADR-0007) | `ports/model.py` is the only model-call seam and records B8 |
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
| Memory/GraphRAG | — Graphiti rejected (Neo4j/FalkorDB only — violates one-Postgres). Cognee 1.x verified to run GraphRAG on one Postgres with opt-in bi-temporal, but red-team verdict: don't adopt at HEAD for an audit-critical tool | bi-temporal `episodes` on Postgres+pgvector using **Graphiti's data model as blueprint**, behind a `MemoryPort`; edge tables and graph traversal are post-v1 (Cognee/LightRAG become optional adapters after a pinned-version spike) |
| MCP governance | FastMCP middleware `on_call_tool` hook (block via ToolError) — the embeddable tiering seam | tool→tier registry + policy middleware + **redundant enforcement in our tool executor** (security boundary never single-sourced in a third-party hook) |
| Approvals | LangGraph `interrupt()` + PostgresSaver (durable suspend/resume); slack-bolt Block Kit. **HumanLayer rejected — repo self-declares deprecated** | single-use approval tokens, 30-min expiry, token→(thread_id, tool_call) binding |
| Audit/replay | LangGraph time-travel (`get_state_history`, fork) as replay backbone | JSONL recorder (source of truth) + model-response recording for deterministic replay |
| Eval | Hand-written deterministic scorer over recorded cases: exact B6 status + required evidence refs; no LLM-as-judge in CI | the v1 acceptance metric is small and deterministic; add an eval library only when a non-trivial metric requires it |
| Observability | OpenTelemetry + OpenInference instrumentation; optional `obs` profile runs Phoenix as the default read-side UI, with Langfuse as an exporter-only swap. JSONL remains authoritative | no runtime dependency on the UI; ADR-0019 amends the earlier UI deferral |
| Ticketing SDKs | `githubkit` (MIT, async — over PyGithub: LGPL + "seeking maintainers") · `atlassian-python-api` · official `asana` | TicketingPort (verified: no OSS unifier covers Linear+GitHub+Jira+Asana — ticketutil has the wrong provider set) + **Linear adapter via direct GraphQL** (no official Python SDK; community `linear-api` stale) |

## 2c. Local observability stack (`local` environment only, via compose profiles)

> **Implementation status:** the commands and service names in §§2c–2e are the locked target
> interface, not a claim that the files already exist. They become runnable at M0 (core), M1
> (`lab`), and M6 (`obs`) respectively.

v1 must be verifiable on a laptop, so the alert sources and tool backends the system talks to
in production need runnable local equivalents. **Not all of them can have one:** Datadog and
PagerDuty are SaaS — there is no local Datadog, and having their cloud webhook back to a
laptop would need a public tunnel. Those two are exercised by **replaying recorded payloads**
at the Receiver, which is precisely what the normalizers and per-source HMAC verification
need tested anyway.

| Purpose | Service | Profile | Notes |
|---|---|---|---|
| Core runtime | postgres+pgvector · redis · app | *(default)* | `docker compose up` — one command, three services |
| Alert source | prometheus + alertmanager | `lab` | Alertmanager sends no HMAC ⇒ network allowlist (§5.1) |
| Log backend | loki + promtail | `lab` | **chosen over ELK**: ~200MB vs 4GB+ heap |
| Fault injection | faultbox | `lab` | sample app that leaks / 500s / stalls on command |

These services fill **two distinct roles**, and the distinction is load-bearing:

1. **Alert sources** fire webhooks at the Receiver (§5.1): Alertmanager.
2. **Tool backends** answer read-tier tool calls (§5.5): `metric query` → Prometheus,
   `log search` → Loki. Both tools were previously named with **no backend behind them**;
   this section is what makes specialist investigation real instead of stubbed.

**No local Grafana.** Alertmanager already fires a real HTTP webhook at the Receiver, so a
second local alert source buys no coverage the first does not already provide; the Grafana
webhook *shape* is what the normalizer must get right, and that is tested by golden fixtures and
by `smokejumper fixtures replay`, like the two SaaS sources. Loki stays, because `log search`
needs a real backend and nothing else in the profile provides one.

**No replayer service.** Recorded Datadog/PagerDuty/Grafana payloads are POSTed by
`smokejumper fixtures replay`, run from the app container. A compose service whose only job is to
run that one command on `up` is boilerplate: it added a service and a whole profile without adding
a capability. The corpus under `fixtures/webhooks/` is unaffected — only the compose service is
gone.

Compose profiles keep the default `docker compose up` at three services; the incident lab stays
out of it.

These services are **local only**. The same tools point at dev/prod backends via environment
config (§2d), and the `lab` profile is refused outside `SMOKEJUMPER_ENV=local`.

**Why this is more than dev convenience:** a faultbox-injected incident has *known ground
truth*, so a run's Conclusion can be scored automatically rather than eyeballed. The lab is
the eval-corpus factory for §8, not a nicety. Note this is unrelated to decision §10.10
(the original LLM-trace UI deferral, later amended by decision §10.14) — that concerns *our*
audit record; this concerns *the systems Smokejumper observes*.

## 2d. Configuration & environments (local · dev · prod)

**Naming discipline first**, because two different things want the word "profile":

- **Compose profiles** (`lab` — §2c, `obs` — §2e) select which *services start*.
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
| Alert sources | `lab` + fixture replay | real webhooks, dev secrets | real webhooks, prod secrets |
| Model roles (§2) | cheap or local model | cheap model | full-strength |
| Spend ceiling | tiny | tiny | real, with kill switch |
| Ticketing (§5.6) | dry-run / fixture | test Linear team | prod Linear team |
| Slack | dev workspace | dev workspace | real workspace |
| Federated MCP (§5.5) | stub descriptor | dev endpoint | prod endpoint |
| Ports (§5.10) | stubs allowed | stubs warn | **security-relevant stubs forbidden** |

### Environment-gated safety rules (enforced at boot, not documented-and-hoped)
- **`prod` refuses to start if any security-relevant port is a stub** (`AllowAll`, `NoopGovernance`,
  `FixturePlatform`). ADR-0004 accepted the risk that "stubs normalize insecurity if deployed
  carelessly" and mitigated it with a loud log line — a log line is not a control. Fail closed.
- **The `lab` compose profile is refused outside `local`.** The faultbox exists to break things;
  it must not be reachable from a real environment.
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

1. **Instrumentation is OpenTelemetry** (OpenInference semantic conventions): spans originate in
   `ports/model.py` and the MCP executor — the two places that already know the model, the
   prompt identity, the token counts, the cost, and the latency. No instrumentation code lives
   in callers.
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

The Agent Registry (§5.3) **references** rather than inlines: `prompt_ref: agents/metrics-analyst@v3`.
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
│                               # profiles: lab (§2c), obs (§2e)
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
│   ├── loki/                   # log store config
│   └── faultbox/               # injectable-fault sample app
├── src/smokejumper/
│   ├── contracts/              # B1–B11 pydantic models — THE source of truth
│   ├── receiver/               # FastAPI app: webhook routes, verify port, normalize, dedupe
│   ├── queue/                  # Redis Streams producer/consumer
│   ├── intelligence/           # LangGraph graph, supervisor, registry loader, sub-agent runner
│   ├── knowledge/              # facade, vector store, recipes (federates via mcp/)
│   ├── mcp/                    # THE MCP domain — one client, one governance seam (§5.5)
│   │   ├── gateway.py          #   the only app MCP client
│   │   ├── tiers.py            #   tier enforcement + redundant executor check
│   │   ├── approvals.py        #   approval broker (B5 token lifecycle)
│   │   ├── manifest.yaml       #   SINGLE tool→tier registry — ours AND federated
│   │   ├── servers/            #   FastMCP servers, in-process (in-memory transport)
│   │   │   ├── metrics/        #     → Prometheus
│   │   │   ├── logs/           #     → Loki
│   │   │   ├── knowledge/      #     → knowledge.search
│   │   │   └── testing/        #     → demo_destructive_noop (ADR-0005)
│   │   └── federated/          #   external servers we consume, never run
│   │       ├── loader.py       #     imports remote toolsets through the same client
│   │       └── descriptors/    #     curlix.yaml, … — config, not code
│   ├── actions/                # deterministic executors: linear, slack receipts, findings
│   ├── recorder/               # flight recorder writer + replay/eval harness
│   ├── governor/               # budgets, circuit breakers, storm brake, scheduler
│   └── ports/                  # auth/governance/tenancy/model interfaces + v1 stubs
├── registry/agents/*.yaml      # declarative specialist definitions (reference prompts)
├── prompts/                    # prompt registry (§2e) — immutable versions, git is SoT
│   ├── supervisor/             #   plan/vN.md, synthesize/vN.md
│   ├── agents/                 #   <agent-name>/vN.md
│   └── CHANGELOG.md
├── recipes/*.yaml              # runbook recipes (procedural memory)
├── scripts/check_doc_contract.py # enforces SPEC-only normative documentation
├── fixtures/webhooks/          # golden per-source payloads (§8) + replay corpus (§2c)
├── tests/                      # unit + contract + replay tests; doc-contract gate exists now
└── evals/                      # recorded cases for the replay harness
```

Not built in v1: `distiller/` and the knowledge-graph tables (decision 17).

Dependency rule: `contracts` imports nothing internal; everything imports `contracts`;
`intelligence` never imports `actions` (only emits B6); `actions` never imports an LLM client.
**`mcp` is the only application package that speaks MCP**—no other package constructs a client.
Every call crosses the manifest tier check and the executor re-check; `knowledge` federates by
calling `mcp`, never by opening its own connection.

## 4. Boundary contracts (B1–B11)

All contracts are pydantic models in `src/smokejumper/contracts/`, versioned with a
`schema_version` field. Breaking changes bump the version; the recorder stores the version
with every payload.

- **B1 · VerifiedInbound** — transport-level: raw body + headers, passed only after the Auth
  port validates the source transport. HTTP webhook adapters verify the source-specific
  signature or configured shared secret; Slack Socket Mode authenticates with the app token
  and does not require an HTTP signing secret. Stub: AllowAll.
- **B2 · AgentEvent** — the single input type intelligence accepts:
  `{id, schema_version, source(grafana|alertmanager|datadog|pagerduty|generic|slack|scheduled), kind(alert|chat|scheduled|storm), source_event_key, fingerprint, severity(critical|high|medium|low|info), title, body, entities[{type,id}], occurred_at, received_at, dedupe_count, raw}`.
  `fingerprint` is SHA-256 of canonical JSON `[source, source_event_key, sorted([[entity.type,
  entity.id], ...])]`—never of title/body text. Normalizers own `source_event_key`: Grafana/
  Alertmanager alert identity, Datadog monitor ID, PagerDuty dedup key, generic caller event ID,
  Slack thread timestamp, or scheduled recipe+window.
- **B3 · retrieve(ctx) → KnowledgeBundle** — `{episodes[], graph_paths[], recipes[], federated[], tokens_used}`; every item carries `{content, source_ref, valid_at, recorded_at, score}`.
- **B4 · ToolCall / ToolResult** — `{run_id, agent, tool, args, tier(read|privileged)}` →
  `{ok, value|error, latency_ms, cost}`. Read tier executes; privileged tier suspends the run.
- **B5 · ApprovalRequest / ApprovalDecision** — request: `{id, run_id, channel_id,
  message_ts, thread_ts, tool_call, tool_call_sha256, reason, requested_at, expires_at(30m)}`;
  decision: `{approved, decided_by, decided_at, token}` where the opaque token is single-use,
  bound to `(channel_id, thread_ts, tool_call_sha256)`, minted by the Auth port, stored only as
  a hash, and consumed by one atomic update. Expiry ⇒ auto-deny.
- **B6 · Conclusion** — the determinism boundary:
  `{run_id, fingerprint, status(root_caused|mitigated|inconclusive|needs_human), confidence(0-1), summary_md, findings[], evidence_refs[], proposed_actions[], tokens_spent, wall_ms}`.
  Nothing downstream of B6 may call a model.
- **B8 · AuditEvent** — `{run_id, seq, ts, actor(block or agent), kind(event|transition|llm_call|tool_call|gate|action), payload, schema_version}`; append-only, async, every block emits.
  `llm_call` payloads additionally carry `{prompt_ref, prompt_sha256, model, request_sha256,
  response, usage{input_tokens,output_tokens}, cost_usd, latency_ms}` (§2e). The recorded
  response is the deterministic replay fixture; configured redaction runs before append.
- **B9 · DistillationCandidate** — a closed case bundle from the recorder → Distiller.
- **B10 · PlatformPort** — external host-platform API (e.g. Curlix): `skills.execute`,
  `assets.query`, `findings.write`. v1 stub: no-op + fixture data.
- **B11 · Assignment / Finding** — assignment: `{agent, question, context_slice, budget{tool_calls, tokens}}`; finding: `{agent, hypothesis, evidence[], confidence, budget_spent}`.

(B7 is intentionally unassigned — reserved, keeps historical numbering from the diagram.)

## 5. Component specifications

### 5.1 Receiver — deterministic, no LLM, no ticket/action writes
- All inbound surfaces implement a **`ChannelAdapter` port** (`listen()` → yields raw
  inbound, `send(receipt)`); **v1 ships exactly one chat adapter: Slack.** Telegram
  (`aiogram`) and email (`imap-tools`/`IMAPClient`) are documented adapter stubs behind
  the same port — designed for, not built (red-team: building them in v1 is scope creep).
- Per-source alert normalizers are hand-written (verified: no OSS library does this),
  **seeded from Alerta's Apache-2.0 `alerta/webhooks/` parsers** (grafana, prometheus,
  pagerduty, cloudwatch, …) with attribution. Signature verification is per-source HMAC,
  also hand-written (Alertmanager sends none — allowlist by network instead).
- One FastAPI route per HTTP source: `/webhooks/grafana`, `/webhooks/alertmanager`,
  `/webhooks/datadog`, `/webhooks/pagerduty`, `/webhooks/generic`. **Slack runs in
  Socket Mode via `slack-bolt`** (a listener task next to FastAPI — no public URL needed;
  inbound events and outbound Web API calls use the same bot). Requires a Slack app Neeraj
  creates once: bot token (`xoxb-`) + app token (`xapp-`, `connections:write`), bot scopes
  `app_mentions:read`, `chat:write`, `channels:history`, `reactions:write` + interactivity
  enabled for the approve/deny buttons.
- Verify via Auth port (B1) → normalize to AgentEvent (B2) → fingerprint → fixed dedupe window
  (15 minutes from the first `received_at`; duplicates do not extend it; an incident close also
  closes it). The same fingerprint increments `dedupe_count` on the open event instead of
  emitting a new one → coalesce storms (>20
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
- Façade: `retrieve(ctx: AgentEvent | str, budget) → KnowledgeBundle`. pgvector similarity over
  `episodes` (closed past incidents) → recipes matched by trigger tags → federated sources
  queried only if local results < threshold. **Federation goes through the one MCP client**
  (§5.5) and is tiered like any other tool call — the façade does not own an MCP client, so
  modality ④ cannot become a second, ungoverned path to an external server.
- Bi-temporal: every episode has `valid_at` + `recorded_at`; retrieval defaults to
  "currently valid" but replay can query "as believed at time T".
- **Graph retrieval is post-v1** (decision 17). `kg_nodes`/`kg_edges` and ≤2-hop expansion over
  `caused_by | fixed_by | applies_to` sit behind `MemoryPort` for a later milestone. B3's
  `graph_paths[]` field stays in the frozen contract and is always empty in v1. Two reasons: the
  three v1 specialists consume episode text and recipes, not paths, and nothing in v1 writes
  edges — the Distiller is post-v1 too, so a graph would be queried empty on every run.
- **Implementation stance (researched):** the store is hand-rolled Postgres tables using
  **Graphiti's bi-temporal data model as the blueprint** (entity/edge with
  valid_at/invalid_at + created_at/expired_at; pgvector embeddings) — Graphiti itself is
  rejected (requires Neo4j/FalkorDB; violates one-Postgres). Everything sits behind a
  `MemoryPort`, so Cognee (verified: single-Postgres GraphRAG, opt-in temporal mode) or
  LightRAG can replace the hand-rolled store later via a pinned-version spike without
  touching callers.

### 5.5 MCP domain — one client, one manifest, two enforcement points

All MCP concerns live in `src/smokejumper/mcp/`. FastMCP implements Smokejumper's own servers and
the application-side client/policy seam; no other package constructs an MCP client (§3).

**Transport.** Our servers are instantiated in the app process and the client reaches them over
FastMCP's in-memory transport (`Client(server)` — same process, no subprocess, no socket, full
MCP session and middleware pipeline; verified at
<https://gofastmcp.com/clients/transports>). Federated servers are the only MCP traffic that
leaves the process: HTTPS with certificate verification to the endpoint in their descriptor.

**Single semantic manifest.** `mcp/manifest.yaml` assigns every local and federated tool a tier
(`read` | `privileged`) and is the only tier source. A tool absent from it fails boot rather than
defaulting to `read`, so a new capability cannot arrive untiered.

**Two enforcement points.** The FastMCP `on_call_tool` middleware refuses a disallowed call by
raising `ToolError`; the application executor independently re-checks the tier from the same
manifest before dispatch. One of the two is a third-party hook, so neither is trusted alone
(ADR-0010). Privileged calls then enter B5. The production privileged tier ships empty; only
`demo_destructive_noop` exists under test configuration.

**v1 read tools:** `metric.query` → Prometheus · `log.search` → Loki · `knowledge.search` →
Knowledge · `change.list` → fixture/local deployment history through `PlatformPort` · Linear
read · recipe read · platform asset query. This gives the Change Auditor a real, bounded source
instead of an unnamed backend.

**Credential and audit rules.** Provider and federated-server credentials resolve through
`EnvCredentials` (§5.10) at call time and never enter a prompt, a tool argument, or a recorded
payload; configured redaction runs before every B8 append (§5.8). A federated descriptor declares
its endpoint and its tool allowlist, so a remote server cannot widen its own surface by
advertising new tools. OTLP spans are read-side telemetry; JSONL remains authoritative.

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
  LangChain v1 `ModelCallLimitMiddleware`/`ToolCallLimitMiddleware`; Smokejumper's Decimal-USD
  ledger is authoritative per run and fails closed for an unpriced prod model. Nothing outside
  the app throttles provider traffic, so that ledger plus the RPM/TPM limiter (§2b) are the only
  spend controls that exist.
- Circuit breakers: 3 consecutive provider failures ⇒ pause consumption 60s and synthesize
  `needs_human` for open runs. Storm brake: queue depth > 25 ⇒ only `critical|high` dequeued.
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

### 5.9 Distiller — post-v1 (decision 17)
Turning closed cases into knowledge is deferred entirely; there is no v1 `smokejumper distill`.
The design it would implement is recorded in ADR-0009 and remains one-way: recorder → knowledge,
never reading chat, with case embeddings and graph edges committing automatically and draft
recipes landing in `recipes/drafts/` for a human to promote.

Every seam it needs already exists, so adding it later is a new module rather than a redesign:
the `runs` index locates a closed run's events (§5.8), B9 `DistillationCandidate` stays reserved
in the frozen contract (§4) alongside B7, and `MemoryPort` (§5.10) owns the write path.

**Consequence, stated plainly:** with no Distiller, nothing in v1 writes `episodes`. Procedural
memory still works — recipes are hand-authored YAML — but episodic retrieval returns whatever was
seeded, and in a fresh deployment that is nothing. The `episodes` table, its embedding call, and
its pgvector index exist in v1 so the schema and the retrieval path are proven and eval cases can
seed them; they are not a self-populating memory yet. §8's eval corpus comes from faultbox ground
truth, which is why no v1 acceptance criterion depends on distillation.

### 5.10 Ports (hexagonal seam)

| Port | v1 implementation | Local/test substitute | Prod gate |
|---|---|---|---|
| `AuthPort` | host-supplied credential/signature verifier | `AllowAll` | `AllowAll` forbidden |
| `GovernancePort` | host-supplied policy identity | `NoopGovernance` | `NoopGovernance` forbidden |
| `TenancyPort` | `SingleTenant` | same | allowed: single tenancy is the v1 contract, not a stub |
| `ModelProvider` | provider SDK client selected per role by config (ADR-0007) | recorded/fake model | fake forbidden |
| `PlatformPort` | host-supplied platform adapter | `FixturePlatform` | fixture forbidden |
| `ChannelAdapter` | Slack Socket Mode | fake channel | fake forbidden when enabled |
| `TicketingPort` | Linear GraphQL | dry-run/fixture adapter | fixture forbidden when enabled |
| `MemoryPort` | Postgres+pgvector bi-temporal episode store | in-memory test adapter | in-memory forbidden |

`EnvCredentials` is the runtime secret resolver used by real adapters; it is not a security
decision and is not itself a stub. Every selected substitute logs its identity at boot.

**Environment gate (§2d):** stub selection is env-aware and enforced, not advisory —
`local` allows stubs, `dev` warns, and **`prod` refuses to boot** while any security-relevant
port is stubbed. A stub that only writes a log line is indistinguishable from a real port to
everything except a human reading logs, which is exactly the failure ADR-0004 flagged and did
not close.

## 6. Sequence flows (level-2)

### 6.1 Alert triage (happy path)
Grafana webhook → Receiver verifies+normalizes → dedupe miss → enqueue → supervisor intake →
retrieve (episodes + recipes; any federated tool crosses the manifest tier check) → plan selects
specialists → parallel Assignments → ModelProvider calls the configured worker model → Findings
back → aggregate → synthesize Conclusion(root_caused, 0.82) →
Actions: create Linear ticket SMOKE-123 + Slack receipt with evidence links → recorder has
the full trace → run closed.

### 6.2 Approval round-trip (v1 test/demo path)
The production privileged tier is empty. The test-only `demo_destructive_noop` proves the full
path: sub-agent requests privileged tool → the tier check suspends the run (LangGraph interrupt persisted) →
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
`episodes` (case embeddings, pgvector, bi-temporal `valid_at`/`recorded_at`) ·
`checkpoints` (LangGraph) · `schema_migrations` (alembic).

`kg_nodes`/`kg_edges` are post-v1 (§5.4, decision 17); no v1 migration creates them.

## 8. Testing & acceptance

Kinds of test, in ascending cost. Every kind except the lab end-to-end runs in CI with no external
account and no live model.

- **Contract tests** — every B-model round-trips JSON, invalid enums and out-of-range values are
  rejected, and `schema_version` is required. Golden payloads per webhook source in
  `fixtures/webhooks/`.
- **Component tests** — fingerprint stability under entity reordering; the dedupe and coalesce
  truth table including the 20-vs-21 fingerprint storm boundary; double delivery ⇒ one ticket;
  approval expiry ⇒ deny; budget breach ⇒ `inconclusive` B6 carrying partial findings.
- **Service-backed tests** — marked `integration`, they skip loudly unless Postgres and Redis are
  reachable. `SMOKEJUMPER_TEST_STACK=1` turns that skip into a failure, which is how CI runs them
  against service containers on loopback. A test that passes because its dependency was absent is
  worse than no test.
- **Replay tests** — five recorded `evals/*.json` cases replay deterministically from the JSONL
  audit record using recorded model and tool responses. CI gate: at least 4 of 5 match the
  expected B6 status and cite the expected evidence refs. The comparison is exact; there is no
  LLM-as-judge.
- **Lab end-to-end** — the faultbox injects a known fault, a Prometheus rule fires, Alertmanager
  posts to `/webhooks/alertmanager`, and the resulting Conclusion is scored against the
  *injected* ground truth. This is the only test where "was the conclusion correct" is
  mechanically answerable, so it produces eval cases instead of them being hand-authored. Not
  CI-gated — it needs the `lab` profile; run it before a release.

**Acceptance (v1 exit).** With the default stack plus the `lab` and `obs` profiles up, all three
acceptance sources — Grafana, Datadog, PagerDuty — are replayed from recorded payloads, each one
twice. Per source that must produce one ticket created on first delivery and updated rather than
duplicated on the second, one Slack receipt, and a complete recorder trace; `smokejumper eval`
must then report at least 4 of 5 cases matching.

**The acceptance trio and the lab end-to-end do different jobs, and they no longer share a
source.** The trio proves three real payload *shapes* normalize and verify correctly, so all three
are replayed rather than fired live: Datadog and PagerDuty are SaaS with no local equivalent, and
Grafana is an alert payload format Smokejumper must normalize, not a system it operates — it is
not a `lab` service. The lab proves the live alert *path* against faultbox ground truth, and
Alertmanager is its source. Alertmanager is therefore never part of the replay trio, and Grafana is
never fired live. Acceptance drives replay through the app container rather than starting the
`fixtures` profile, because the profile's `replayer` runs the same command (§12 M1).

§12 owns the exact command sequence, the evidence files it must leave behind, and the rollback
path.

## 9. Milestones (each independently verifiable)

Seven milestones, strict M0→M6 order, each landing as one reviewed PR. **This list is an index;
§12 is normative** for deliverables, exit criteria, commands, and evidence. A milestone is
complete when §12's exit evidence for it exists.

- **M0** — the stack boots. Package and CI, boundary contracts, layered configuration, ports and
  their environment gates, the three-service Compose stack, first migration, `/healthz`, and a
  `prod` that refuses to start unsafe.
- **M1** — an alert becomes a recorded, queued event. Flight Recorder, Receiver and normalizers,
  fingerprint/dedupe/storm, Redis Streams, and the `lab` + `fixtures` profiles.
- **M2** — one alert reaches one ticket. `ModelProvider` against the chosen provider, supervisor
  graph, one specialist, Slack receipt, Linear create-vs-update.
- **M3** — retrieval is real. `episodes` similarity plus recipes behind `MemoryPort`, cited in B6.
- **M4** — investigation is parallel and bounded. Three specialists, the spend ledger, Governor.
- **M5** — tools are governed. MCP manifest, in-process FastMCP targets, two independent tier
  checks, and the approval round-trip.
- **M6** — the result is reproducible. Replay, eval, `obs` traces, and release proof.

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
10. **Original observability decision (amended by 14)** — JSONL stays the audit source of
    truth. The original platform/UI deferral was later narrowed: decision 14 permits the
    optional Phoenix read-side while preserving this source-of-truth rule.

Added 2026-07-25 (architecture update):

11. **Local observability stack in compose profiles** (§2c, ADR-0016) — Prometheus+Alertmanager,
    Grafana, Loki+Promtail and a faultbox run under a `lab` profile so alert sources and tool
    backends are real locally; Datadog/PagerDuty are SaaS and get a `fixtures` replayer
    instead. Loki over ELK on footprint. *Amended by 17: Grafana left the `lab` profile, the
    `fixtures` profile and its replayer service went away, and the default stack stayed at three
    services.*
12. **One application MCP domain** (§5.5, ADR-0017) — `hub/` and the `knowledge/` federated
    client collapse into `src/smokejumper/mcp/`: one client, one governance seam, one central
    tier manifest, our servers in-process, federated servers as descriptors. This closes a path
    where knowledge federation reached an external server without a tier check. *Amended by 17
    in framing only: the single client reaches our servers in-process and federated servers
    directly, rather than through a proxy's virtual MCP endpoint. Deferring the proxy removed a
    network tier, not the seam — the client, the manifest, and tier-checked federation all
    stand, which is the property ADR-0017 exists to protect.*
13. **Layered per-environment config** (§2d, ADR-0018) — `local`/`dev`/`prod` selected by
    `SMOKEJUMPER_ENV`, layered `base.yaml` → `<env>.yaml` → env vars → flags into one
    validated settings object; secrets by reference only. Deliberately distinct from compose
    profiles, which select services rather than values. Prod fails closed on security-relevant stubs and on
    a missing spend ceiling, and the `lab`/`fixtures` profiles are refused outside `local`.
    *Amended by 17: the `fixtures` profile no longer exists, so `lab` is the only profile
    refused outside `local`. The fail-closed rules are unchanged.*
14. **Observability via an OTel seam** (§2e, ADR-0019) — instrument application semantics in the
    model port and MCP executor; Phoenix is the default backend behind an `obs` profile (single
    container, eval-first) with Langfuse as a config-only swap. Amends ADR-0012's "no trace UI in
    v1" while keeping JSONL authoritative. Phoenix is ELv2 — source-available, not OSI. LangSmith
    rejected: proprietary + data egress. *Amended by 17: there is no proxy tier to instrument, so
    the model port and MCP executor are the only span origins.*
15. **Prompts are versioned artifacts in git** (§2e, ADR-0020) — `prompts/` is the source of
    truth, versions are immutable, the registry references instead of inlining, and every
    `llm_call` records `prompt_ref` + `prompt_sha256` so regressions are attributable and
    replay can assert prompt identity. Platform prompt registries rejected as the store.
16. **agentgateway is the LLM/MCP proxy — SUPERSEDED by 17 (2026-07-26); never implemented.**
    The original decision made stable agentgateway v1.3.1 a core sidecar: `ModelProvider` calling
    virtual models, the only app MCP client calling a virtual MCP endpoint, CEL policy generated
    from the manifest, and provider/MCP credentials living only in the sidecar. Recorded here
    because the evaluation is reusable, not because it holds; ADR-0021 keeps the spike evidence
    and now states what would justify adopting it.

Amended 2026-07-26 (subtraction pass, approved by Neeraj):

17. **Layers removed from v1.** The design had accreted for months without a single removal, and
    each of these cost more than it returned at v1 scale:
    - **agentgateway deferred** (supersedes 16, amends 12; ADR-0021 is now Deferred). Its commissioned
      security review returned "conditional accept; not safe as currently specified" with eight
      High findings; §5.5 already conceded that the app stays authoritative for every semantic
      decision the proxy duplicated; and it made M0 unbuildable, because M0 generated proxy
      policy from a manifest that does not exist until M5. v1 instead: `ModelProvider` calls the
      provider SDK behind `ports/model.py`, and FastMCP servers run in-process behind the one app
      MCP client. Default Compose is three services. Virtual models, virtual MCP, CEL
      authorization, the proxy config generator, and its drift check are out of v1 scope.
    - **Graph tables deferred** (narrows 7; ADR-0009). v1 knowledge is `episodes` (pgvector
      similarity) plus recipes. `kg_nodes`/`kg_edges` and ≤2-hop expansion move post-v1 behind
      `MemoryPort`; `episodes` keeps `valid_at`/`recorded_at`, so bi-temporal replay survives.
    - **Grafana dropped from the `lab` profile** (amends 11; ADR-0016). Prometheus and
      Alertmanager fire webhooks at the Receiver directly; the Grafana payload shape is covered
      by golden fixtures and `smokejumper fixtures replay`. Loki stays — `log.search` needs a
      real backend.
    - **The `fixtures` compose profile removed** (amends 11 and 13). Its only service was the app image
      running `smokejumper fixtures replay`, which acceptance invokes directly anyway — a service
      and a profile for zero capability. The corpus under `fixtures/webhooks/` stays; it is what
      the golden per-source tests read.
    - **Distiller deferred entirely** (§1, §5.9). There is no v1 `distill` command. §8's eval
      corpus comes from faultbox ground truth, not from distillation, so it was carrying no v1
      acceptance criterion. The cost is explicit in §5.9: nothing in v1 writes `episodes`, so
      episodic retrieval returns only what was seeded.
    Kept deliberately: `prompt_ref` + `prompt_sha256` on every `llm_call` (decision 15). It is
    one hash per call and it is what makes deterministic replay — the product claim — checkable.

## 11. Build prerequisites and operator inputs

This section is the canonical answer to **“what is needed?”** An implementer may build M0 and
M1 with no external SaaS account. Human-owned credentials first become an exit dependency in
M2, when a real model call, Slack receipt, and Linear issue must cross the system boundary.

### 11.1 Workstation and repository prerequisites

| Requirement | Minimum contract | Needed by | Preflight |
|---|---|---:|---|
| Git | working clone with push access | M0 | `git status --short --branch` |
| Python | CPython 3.12+ | M0 | `python3.12 --version` |
| uv | current version able to resolve and lock Python 3.12 dependencies | M0 | `uv --version` |
| Docker | running daemon with Compose profile support and at least 4 GiB assigned | M0 | `docker info && docker compose version` |
| Free host ports | the ports §11.2 publishes for the profiles being started | M0 | `python3 scripts/check_host_ports.py` |
| Disk | at least 10 GiB free for images, volumes, logs, and eval fixtures | M0 | `df -h .` |
| Node + npx | only for regenerating the Mermaid SVG; not an app runtime dependency | docs only | `node --version && npx --version` |

### 11.2 Network port contract

The table below is the **only normative port inventory**. Compose, health checks, deployment
manifests, and `scripts/check_host_ports.py` must match it. One rule governs it: **a default
`docker compose up` publishes exactly one port — the app's `8000` — and every published port
binds `127.0.0.1`, never `0.0.0.0`.** Everything else is reached on the Compose network by
service name, which is all the app needs; publishing it would widen the attack surface for a
human's convenience only.

| Component / listener | Profile | Bind inside deployment | Protocol / probe | Local host publication | dev/prod exposure | Consumer |
|---|---|---|---|---|---|---|
| Smokejumper API | default | `app:8000` | HTTP; `GET /healthz` | `127.0.0.1:${APP_HOST_PORT:-8000}:8000` | ingress/LB `443 → 8000`; only webhook/API routes | webhook sources, operator |
| Postgres | default | `postgres:5432` | PostgreSQL; `pg_isready` | none | private data network only | app |
| Redis | default | `redis:6379` | RESP; `PING` | none | private data network only | app |
| Prometheus | `lab` | `prometheus:9090` | HTTP | `127.0.0.1:${PROMETHEUS_HOST_PORT:-9090}:9090` | private observability network | `metric.query` tool, lab operator |
| Alertmanager | `lab` | `alertmanager:9093` | HTTP | none | private observability network | Receiver |
| Loki | `lab` | `loki:3100` | HTTP | none | private observability network | `log.search` tool |
| Promtail | `lab` | no listener | outbound push to Loki | none | internal only | Loki |
| faultbox | `lab` | `faultbox:8080` | HTTP | none | forbidden outside `local` | lab operator |
| replayer | `fixtures` | no listener | outbound HTTP to app | none | forbidden outside `local` | Receiver |
| Phoenix UI | `obs` | `phoenix:6006` | HTTP | `127.0.0.1:${PHOENIX_HOST_PORT:-6006}:6006` | authenticated internal UI if enabled | operator |
| Phoenix OTLP | `obs` | `phoenix:4317` | OTLP/gRPC | none | internal observability network | app |
| Provider / Slack / Linear APIs | — | remote `443` | HTTPS/WSS with certificate verification | outbound only | egress allowed from app | `ModelProvider`, Channel/Ticketing adapters |

Two further ports are published, both under opt-in profiles and both because a human rather
than the app is the consumer: Prometheus `9090` under `lab`, since with Grafana dropped it is
the only UI that shows whether an alert rule actually fired; and Phoenix `6006` under `obs`,
which exists solely to be read in a browser. Phoenix's OTLP `4317` stays unpublished because
the app exports to `phoenix:4317` in-network.

v1 has **no MCP listener at all**: FastMCP servers are served in-process and the single app MCP
client reaches them without a socket. Faults are injected by executing inside the faultbox
container, not through a published port. Inspecting Postgres or Redis from the host is a
per-developer opt-in in the git-ignored `docker-compose.override.yml` (§2d), never a committed
default. Host-port overrides belong in the untracked local `.env`; service-to-service URLs
always use stable service names and container ports.

**Preflight.** `python3 scripts/check_host_ports.py [--profiles lab,fixtures,obs]` checks only
the ports the requested profiles publish, names the owning service and — where discoverable —
the local process holding the port, prints the exact override variable to set (for example
`PHOENIX_HOST_PORT=16006`), and exits non-zero so it can gate. It imports only the standard
library, so it runs before `uv sync`. `tests/scripts/test_check_host_ports.py` parses the table
above and fails when it and the script's inventory disagree, so this contract cannot decay into
prose-only truth.

**This workstation, verified 2026-07-26 via `lsof -nP -iTCP -sTCP:LISTEN`:** `127.0.0.1:3000`
(a Python process), `127.0.0.1:6006` and wildcard `*:8080` (both Docker) are occupied. Only
Phoenix is affected and needs `PHOENIX_HOST_PORT`; `3000` and `8080` were previously published
by Grafana and the faultbox and are now published by nothing. An earlier revision of this
section named `3000` and `6006` while missing `8080` — the preflight exists so that class of
omission cannot ship again.

### 11.3 Accounts, credentials, and identifiers

Secret values are injected at runtime and are never committed. Tests use fakes or fixture
secrets. A missing optional integration disables that adapter; a missing credential for an
enabled adapter fails boot with the variable name, never during an incident.

| Input | Exact configuration surface | Needed by | Owner action / local fallback |
|---|---|---:|---|
| One LLM provider | `SMOKEJUMPER__MODEL__API_KEY` carries the provider key to the app process; `ModelProvider` passes it to the SDK explicitly rather than relying on the SDK's ambient variable, so the key has exactly one name here. Provider and role model identifiers are non-secret values under `model:` in `config/<env>.yaml` (§2d) | M2 | Choose one live provider and its worker/synthesis model strings. Tests use recorded responses; a local Ollama endpoint needs no key. |
| Embedding model | concrete embedding model under `model:` in `config/<env>.yaml` plus `SMOKEJUMPER__EMBEDDING__DIMENSION` | M3 | Choose before the pgvector migration; **the dimension is immutable without a migration.** Recommended default: a 1536-d model from the provider already selected. |
| Spend ceiling | `SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN` | M2 | Explicit in every environment. Local default: `1.00`; dev default: `2.00`; prod has no default and fails closed. |
| Slack bot token | `SLACK_BOT_TOKEN` (`xoxb-…`) | M2 | Create/install one Slack app in the development workspace. |
| Slack app token | `SLACK_APP_TOKEN` (`xapp-…`, `connections:write`) | M2 | Enable Socket Mode and create the app-level token. No `SLACK_SIGNING_SECRET` is required for the v1 Socket Mode transport. |
| Slack channel | `SMOKEJUMPER__SLACK__CHANNEL_ID` | M2 | Choose a development channel and invite the bot. Private-channel support needs `groups:history` and is outside the default scope. |
| Slack scopes/features | app config, not an env value | M2/M5 | Bot scopes: `app_mentions:read`, `chat:write`, `channels:history`, `reactions:write`; enable interactivity for approval buttons. |
| Linear API key | `LINEAR_API_KEY` | M2 | A personal API key is the v1 single-tenant choice; OAuth is post-v1 distribution work. |
| Linear team | `SMOKEJUMPER__TICKETING__TEAM_ID` | M2 | Choose the development team UUID. The adapter discovers and validates workflow-state IDs at boot. |
| Linear project | `SMOKEJUMPER__TICKETING__PROJECT_ID` | M2 | Optional; omit to create team-level issues. |
| Webhook verification | `SMOKEJUMPER__WEBHOOKS__<SOURCE>__SECRET` for Grafana, Datadog, PagerDuty, and generic HTTP | M1 tests; dev/prod live intake | Local fixtures use non-secret test values. Alertmanager has no signature and is accepted only from the configured network allowlist. |
| Postgres / Redis | `SMOKEJUMPER__DATABASE__URL`, `SMOKEJUMPER__REDIS__URL` | M0 | Compose supplies local values. dev/prod need managed endpoints, credentials, and TLS policy. |
| Prometheus / Loki | `SMOKEJUMPER__TOOLS__PROMETHEUS_URL`, `SMOKEJUMPER__TOOLS__LOKI_URL` plus optional auth headers | M1/M5 | Compose supplies local URLs. dev/prod require real backend endpoints and read-only credentials. |
| Federated MCP server | descriptor endpoint, auth reference, and tool allowlist under `mcp/federated/descriptors/` | M5 | Local uses a stub descriptor. Real endpoints are not required for v1 acceptance. |
| OTLP exporter | `OTEL_EXPORTER_OTLP_ENDPOINT` plus backend auth if needed | M6 | Local Phoenix is credential-free. A remote backend is optional. |

Official setup references used to lock these inputs:

- Slack Socket Mode: <https://docs.slack.dev/tools/bolt-python/concepts/socket-mode/>
- Linear GraphQL authentication and team IDs: <https://linear.app/developers/graphql>
- Docker Compose profiles: <https://docs.docker.com/compose/how-tos/profiles/>
- Pydantic settings sources: <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>

### 11.4 Owner checklist—the only inputs an agent cannot manufacture

- [ ] **By M2:** choose the live LLM provider and exact worker/synthesis model strings; provide
  one provider key to the app process and confirm the local spend ceiling.
- [ ] **By M2:** create the Slack app, enable Socket Mode + interactivity, apply the four bot
  scopes above, install it, invite it to the development channel, and provide the two tokens
  plus channel ID through the runtime environment.
- [ ] **By M2:** choose the Linear development team; provide a personal API key and team UUID.
- [ ] **By M3:** confirm the embedding provider/model and vector dimension before the pgvector
  migration. This is the only remaining schema-shaping owner input.
- [ ] **Only for dev/prod:** provide managed Postgres/Redis, read-only Prometheus/Loki, live
  webhook secrets/allowlists, and the real implementations selected for security-relevant
  ports.

Datadog and PagerDuty accounts, public tunnels, a production secret manager, real privileged
tools, and a federated MCP server are **not prerequisites for local v1 acceptance**.

### 11.5 Defaults locked for implementation

These low-cost details were previously implicit; they are now explicit so an implementer does
not have to invent them:

1. `SPEC.md` owns all current build/run facts; README never owns a parallel quickstart.
2. v1 acceptance targets the local single-tenant deployment. `prod` config is a fail-closed
   contract and intentionally will not boot until real Auth/Governance/Platform adapters are
   supplied; building those adapters is not silently added to v1.
3. Slack v1 is Socket Mode only. The app token authenticates the WebSocket transport; there is
   no HTTP Slack event endpoint and no Slack signing-secret requirement.
4. Linear uses a personal API key and one configured team. OAuth/multi-workspace installation
   is post-v1.
5. `AgentEvent.kind` includes `storm`; a coalesced storm is not disguised as a normal alert.
6. Generic HTTP webhooks use `X-Smokejumper-Signature: sha256=<hex>` over the raw request body
   with the configured shared secret. Vendor adapters follow each vendor's documented scheme.
7. Approval tokens are opaque 256-bit random values; only a hash is stored with the bound
   `(thread_id, tool_call)` and expiry. Consumption is one atomic database update, so no token
   signing key is required.
8. Exact third-party versions are not guessed in prose. M0 verifies official compatibility,
   pins them in `pyproject.toml`, and commits `uv.lock`; the lockfile is executable truth.

## 12. Executable implementation plan

**This section is normative for build order, deliverables, exit criteria, commands, and
evidence**; §9 is an index into it. Implementation is seven milestone PRs in strict M0→M6 order.
Every work packet uses the same loop: **write one behavioral test → run it and observe the
expected failure → implement the minimum → run the focused test → run the universal gates →
commit**. Framework calls are checked against current official documentation before code is
written; the URL and any non-obvious lifecycle constraint go in the implementing module's
docstring.

**Each milestone consumes only artifacts an earlier milestone produced.** That property is what
makes the order buildable, and it is why the MCP manifest, the FastMCP targets, and tier
enforcement all arrive at M5 rather than being asserted earlier against files that do not exist.

**Everything below is planned.** At this revision the repository contains
`src/smokejumper/__init__.py`, `scripts/check_doc_contract.py`, `tests/`, and `pyproject.toml`
with `uv.lock`; the five universal gates run and pass, and the declared `smokejumper` console
script does not yet import because M0.1 has not landed. A command stops being planned when its
milestone's exit evidence exists — not when it looks correct.

### Universal gates

Five gates. All must exit 0 before any commit:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
python3 scripts/check_doc_contract.py
```

This is the entire enforced set and CI runs exactly these, so the list cannot drift from what is
actually checked. `pytest` also invokes the documentation-contract checker, which is why a
docs-only change still runs the whole set. Compose-changing packets additionally run
`docker compose config`.

### Where a command runs

Decided once, because getting it wrong produces commands that cannot work:

- **On the host:** anything that only touches the repository — `uv run …`, `git`, the five
  gates, and `docker compose` itself.
- **Inside the deployment:** anything that must resolve `postgres`, `redis`, or `app`. Compose
  service names do not exist on the host, so a host-run `uv run smokejumper …` cannot reach the
  stack. Use `docker compose exec -T app …`; `-T` disables TTY allocation so the command works
  non-interactively and its stdout can be captured.
- **CI is the exception:** Postgres and Redis are GitHub Actions service containers published on
  loopback, so host-run `pytest` reaches them. CI sets `SMOKEJUMPER_TEST_STACK=1`, which turns
  the `integration` and `e2e` skips into hard requirements (§8).

A command that runs inside the deployment needs its data there. The app image carries `config/`,
and each later milestone adds the read-only data it creates — `prompts/`, `registry/`,
`recipes/`, `fixtures/`, `evals/` — because replay, fixture replay, and eval all run inside.

### Exit evidence

Each milestone writes its evidence to `.artifacts/verification/<milestone>/<git-sha>/`, where
`<milestone>` is `m0` through `m6`. Every milestone captures the gate output there, and from M0
onward `alembic current`, because rollback has to know which schema revision a milestone left
behind:

```bash
EVIDENCE=".artifacts/verification/m0/$(git rev-parse --short HEAD)"   # m0 … m6
mkdir -p "$EVIDENCE"
{ uv run pytest && uv run ruff check . && uv run ruff format --check . \
  && uv run pyright && python3 scripts/check_doc_contract.py; } 2>&1 | tee "$EVIDENCE/gates.txt"
```

`.artifacts/` is git-ignored and the M0.1 CI workflow uploads it as a build artifact, so evidence
outlives the machine without entering the repository. Each milestone below names the files it adds
beyond `gates.txt` and `alembic-head.txt`.

### Teardown and rollback

`docker compose down -v` **deletes the Postgres and Redis volumes.** It is teardown, not cleanup,
and it is never run against the default project name. CI wants a disposable stack, so it opts in
explicitly with its own project name on both ends of the job:

```bash
PROJECT="smokejumper-ci-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
docker compose -p "$PROJECT" up -d --build
docker compose -p "$PROJECT" down -v
```

Rolling a milestone back preserves data. Migrations come down *before* the code that defines them
goes away, because the older checkout does not contain the newer revision script:

```bash
PREVIOUS_HEAD="$(cat .artifacts/verification/m3/<sha>/alembic-head.txt)"   # the target milestone's
docker compose exec -T app alembic downgrade "$PREVIOUS_HEAD"
docker compose down                       # containers removed, named volumes kept
git checkout v1-m3
docker compose up -d --build
docker compose exec -T app alembic current               # expect $PREVIOUS_HEAD
curl --fail --silent "http://127.0.0.1:${APP_HOST_PORT:-8000}/healthz"
```

Each milestone is tagged `v1-m<N>` on merge, so the rollback target is a real ref instead of a
commit someone has to go find mid-incident.

### M0—foundation, contracts, configuration, and core runtime

M0 proves four things and nothing else: the three-service stack boots, its schema applies,
`/healthz` answers, and `prod` refuses to start when it is unsafe. There is no proxy, no generated
configuration, and no MCP at M0.

**M0.1 · CLI entry point and CI**
- Create: `src/smokejumper/cli.py` (Typer), `Dockerfile`, `.dockerignore`,
  `tests/test_package.py`, `.github/workflows/ci.yml`. `pyproject.toml`, `uv.lock`, `.gitignore`,
  `scripts/check_doc_contract.py`, and `tests/test_doc_contract.py` already exist; they are wired
  into CI, not created.
- RED: `smokejumper --help` fails to import `smokejumper.cli`, and no workflow runs the gates.
- GREEN: the declared console script resolves. CI runs the five universal gates on Python 3.12
  with Postgres+pgvector and Redis service containers on loopback and `SMOKEJUMPER_TEST_STACK=1`,
  then uploads `.artifacts/`. Commit: `build: add CLI entry point and CI workflow`.

**M0.2 · One validated settings object**
- Create: `src/smokejumper/config.py`, `config/{base,local,dev,prod}.yaml`, `.env.example`, the
  `smokejumper check-config` command, `tests/test_config.py`.
- RED: precedence tests cover defaults < `base.yaml` < `<env>.yaml` < env vars < CLI flags.
  Malformed config, a stubbed security-relevant port under `prod`, a missing `prod` spend ceiling,
  and a `lab` or `fixtures` profile outside `local` must each fail boot.
- GREEN: pydantic-settings custom sources, one startup validator, and a `check-config` command
  that exits non-zero on any of those. Commit: `feat: add layered fail-closed configuration`.

**M0.3 · Boundary contracts**
- Create focused modules under `src/smokejumper/contracts/` for inbound, events, knowledge,
  tools, approvals, conclusions, audit, assignments, platform, and ticketing; add matching
  `tests/contracts/` files and JSON fixtures.
- RED/GREEN one B-contract at a time: valid JSON round-trip, invalid enum/range rejected,
  `schema_version` required, raw inbound bytes encoded explicitly, and B7 absent by design.
- Commit in coherent groups, ending with `feat: define versioned boundary contracts`.

**M0.4 · Hexagonal ports and environment stubs**
- Create: `src/smokejumper/ports/{auth,governance,tenancy,model,platform,ticketing,memory,channel}.py`,
  `src/smokejumper/ports/stubs.py`, `tests/ports/test_stubs.py`.
- RED: local accepts loud stubs; dev warns; prod rejects every security-relevant stub.
- GREEN: protocols plus the smallest stubs that satisfy them. `ports/model.py` is declared here
  and implemented at M2. Commit: `feat: add environment-gated ports`.

**M0.5 · App, persistence, and the three-service Compose stack**
- Create: `src/smokejumper/app.py`, `src/smokejumper/persistence/database.py`, `alembic.ini`,
  `migrations/` with the first revision, `docker-compose.yml`, `tests/test_health.py`,
  `tests/integration/test_stack.py`.
- RED: `GET /healthz` 404s, no schema exists, and `SMOKEJUMPER_ENV=prod` boots happily.
- GREEN: SQLAlchemy 2 async + psycopg 3 + Alembic against Postgres 16 with pgvector, plus Redis.
  Default `docker compose up` starts exactly three services — `postgres`, `redis`, `app` — and
  `/healthz` returns 200 only when the schema is at head and both backing services answer.
  Commit: `feat: boot the three-service core stack`.

**M0 exit evidence** — `gates.txt`, `compose-config.txt`, `healthz.json`, `alembic-head.txt`,
`prod-fail-closed.txt`:

```bash
docker compose config | tee "$EVIDENCE/compose-config.txt"
docker compose up -d --build
curl --fail --silent "http://127.0.0.1:${APP_HOST_PORT:-8000}/healthz" | tee "$EVIDENCE/healthz.json"
docker compose exec -T app alembic current | tee "$EVIDENCE/alembic-head.txt"
docker compose run --rm \
  -e SMOKEJUMPER_ENV=prod \
  -e SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN= \
  app smokejumper check-config 2>&1 | tee "$EVIDENCE/prod-fail-closed.txt"   # must exit non-zero
docker compose down
```

### M1—recorder, receiver, queue, and local incident lab

1. **Recorder first:** `recorder/writer.py`, `recorder/broadcast.py`, the `runs`-index migration,
   `smokejumper logs --follow`, and `smokejumper runs latest --format id`. Tests: append-only
   JSONL, monotonic per-run `seq`, process-unique files, byte offsets, failure counter.
   `runs latest --format id` prints one run id and nothing else, because the acceptance set
   consumes its stdout.
2. **Inbound persistence:** events and quarantine migration plus repository; 401 with an audit
   entry for an unverifiable payload, 202 with a quarantine row for an unparseable one.
3. **Normalizers:** generic, Grafana, Datadog, PagerDuty, and Alertmanager adapters built from
   `fixtures/webhooks/`; per source a golden valid payload, an invalid one, a signature case, and
   a severity-mapping case. Grafana is a payload format here, not a service Smokejumper runs.
4. **Fingerprint, dedupe, storm:** canonical entity ordering, stable hash, the 15-minute window,
   the 20-vs-21 fingerprint boundary, the five-minute reset, and exactly one `kind=storm` enqueue.
5. **Redis Streams:** producer, the `intelligence` consumer group, at-least-once reclaim,
   `event.id` idempotency, max in-flight 3.
6. **`lab` and `fixtures` profiles:** `compose/{prometheus,alertmanager,loki,promtail,faultbox}/`
   and their provisioning. Prometheus rules fire at Alertmanager, which posts directly to
   `/webhooks/alertmanager`; no dashboard sits on the alert path. The `fixtures` profile's
   `replayer` is the app image running `smokejumper fixtures replay`, not a second
   implementation. Fix the faultbox's fault-injection route in this packet and record it — no
   later milestone may invent one.

Commit each numbered packet separately.

**M1 exit evidence** — `gates.txt`, `alembic-head.txt`, `storm-test.txt` (the focused storm test
output) and `alertmanager-to-queue.txt`: `docker compose exec -T redis redis-cli XLEN agentevents`
before and after a faultbox-triggered Alertmanager delivery, plus the AuditEvent recorded for that
event. M1 exits only when both are retained.

### M2—one complete intelligence-to-action path

1. **Prompt and registry seed:** immutable `prompts/supervisor/{plan,synthesize}/v1.md`,
   `prompts/agents/metrics-analyst/v1.md`, `prompts/CHANGELOG.md`, and
   `registry/agents/metrics-analyst.yaml`. Boot resolves every `prompt_ref` and computes its
   `prompt_sha256`, failing on a dangling reference.
2. **`ModelProvider`:** the provider SDK is imported in `ports/model.py` and nowhere else, and a
   test asserts that. Every call records `prompt_ref`, `prompt_sha256`, model, `request_sha256`,
   the response, usage, latency, and a `Decimal` cost into B8 — the recorded response is M6's
   replay fixture, so this is not optional telemetry. Unit tests run against recorded responses;
   CI makes no live provider call. This packet adds the provider SDK dependency.
3. **Single-specialist graph:** intake → retrieve (empty bundle) → plan → dispatch one Metrics
   Analyst → aggregate → synthesize B6, on the Postgres checkpointer, with a restart test proving
   a suspended run survives process death.
4. **Slack adapter:** async Bolt Socket Mode mention listener, thread receipts, and button
   callback plumbing behind `ChannelAdapter`; contract tests use a fake Slack client.
5. **Linear and Actions:** the provider-neutral `TicketingPort` conformance suite, the direct
   GraphQL adapter, fingerprint lookup, create-vs-update, and `(fingerprint, run_id)` idempotency.
   GraphQL `errors` are inspected even on HTTP 200.
6. **Golden end-to-end:** one fixture alert yields one recorded run, one B6, one ticket, and one
   Slack receipt; redelivering the same payload updates instead of duplicating.

The three owner inputs in §11.3 — provider credential, Slack app, Linear key — become blocking
here. Every packet is buildable against fakes; only the live smoke needs them.

**M2 exit evidence** — `gates.txt`, `alembic-head.txt`, `golden-run.jsonl` (the complete recorded
run) and `ticket-idempotency.txt` (the two recorded `action` events showing one create then one
update for the same fingerprint).

### M3—episode retrieval and recipes

1. Confirm §11.3's embedding model and dimension, route `ModelProvider.embed` through it, then add
   the `episodes` migration at that pgvector dimension with bi-temporal `valid_at` /
   `recorded_at`. The dimension is immutable without a migration, so it is settled before this
   packet rather than during it. **Graph tables are deferred past v1:** there is no
   `kg_nodes`/`kg_edges` migration, and `KnowledgeBundle.graph_paths` is returned empty.
2. `MemoryPort` Postgres adapter: episode similarity search, and invalidation that supersedes a
   belief by recording a new row rather than deleting the old one — replay must still be able to
   ask what was believed at time T.
3. Recipe loading and validation from `recipes/*.yaml` with trigger-tag matching.
4. Compose `retrieve()` under a token and item budget into B3 with source refs and scores. The
   `federated` list stays empty until M5, returned by a stub inside `knowledge/`; `knowledge`
   never opens an MCP connection of its own.
5. Re-run the M2 golden case seeded with two episodes and one recipe: B6 must cite the returned
   source refs, and the recorder must hold the exact bundle that was retrieved.

**M3 exit evidence** — `gates.txt`, `alembic-head.txt`, `knowledge-bundle.json` (the recorded B3
bundle) and the B6 that cites it.

### M4—parallel specialists, budgets, and Governor

1. Immutable prompts and registry entries for Log Analyst and Change Auditor; DB, Code, and
   Precedent agents stay present with `enabled: false`. Change Auditor gets only bounded
   `change.list` through the local `PlatformPort` fixture. Validate tool allowlists and budgets
   against the registry schema.
2. Dispatch three B11 Assignments concurrently and aggregate findings in registry-stable order.
   Prove parallelism with a barrier, not a wall-clock comparison.
3. Call-count middleware plus the hand-written token and USD ledger. A breach must synthesize an
   `inconclusive` B6 carrying the partial findings — never a silent death.
4. Provider circuit breaker, max in-flight, and the queue-depth storm brake, with a test at each
   threshold boundary rather than only past it.
5. Scheduler jobs (§5.7) for registry sync and approval expiry; scheduled investigations stay
   recipe-driven and produce ordinary B2 events.

**M4 exit evidence** — `gates.txt`, `parallel-dispatch.txt` (the barrier test proving three
concurrent assignments) and `budget-breach.txt` (the `inconclusive` B6 with partial findings).

### M5—governed tools and the approval round-trip

1. **Manifest:** `mcp/manifest.yaml` plus its loader. Boot and CI fail on an unknown tool, a
   duplicate name, a missing tier, or a registry tool absent from the manifest. The manifest is
   hand-maintained and is the only tool→tier registry; nothing generates a second policy file.
2. **In-process targets:** bounded FastMCP servers for `metric.query` (Prometheus), `log.search`
   (Loki), `knowledge.search`/`knowledge.expand`, `change.list` (the `PlatformPort` fixture),
   Linear read, and recipe read. They run inside the app process, and the single client in
   `mcp/gateway.py` is the only MCP client any package constructs.
3. **Two independent checks:** FastMCP middleware `on_call_tool` denies by tier, and the
   application executor re-checks the tier before dispatch. Prove each denies alone — a call that
   slips past the middleware is still refused by the executor, and a call that bypasses the
   executor is still refused by the middleware. Neither layer may be the only enforcement.
4. **Federated descriptors:** `mcp/federated/loader.py` imports a remote toolset through the same
   client, the same manifest, and the same executor check, with prefixed tool names and a
   descriptor allowlist. A stub descriptor satisfies v1; a real endpoint is not an acceptance
   prerequisite.
5. **Privileged tier:** add `demo_destructive_noop` under test configuration only. The production
   privileged manifest stays empty, which is the promise in §1.
6. **Approvals:** opaque token mint and single-use consume, 30-minute expiry, Slack buttons,
   LangGraph interrupt and resume, restart durability, deny, expiry auto-deny, replay, and a
   double-click race test proving exactly one consumption.

**M5 exit evidence** — `gates.txt`, `tier-denials.txt` (both single-layer bypass attempts failing)
and `approval-round-trip.txt` (mint, approve, consume, and the second attempt being refused).

### M6—replay, eval, traces, and release proof

The Distiller is deferred past v1 and is not an M6 deliverable.

1. Deterministic `smokejumper replay <run_id>` from the JSONL sink plus the runs index, using the
   recorded model and tool outputs. Live re-execution is a separate explicit opt-in, never the
   default.
2. Five `evals/*.json` cases and `smokejumper eval`, reporting per-agent hit rate against recorded
   ground truth. CI requires at least 4 of 5 with no live model. `evals/` ships in the app image,
   because `eval` runs inside the deployment.
3. Application semantic spans at `ports/model.py` and the MCP executor, exported over OTLP, with
   Phoenix under the `obs` profile. Prove JSONL stays complete with Phoenix stopped: nothing may
   depend on a trace being queryable.
4. The faultbox release case end to end — injected fault → Prometheus rule → Alertmanager →
   parallel investigation → grounded B6 → one Linear ticket → Slack receipt → JSONL replay →
   comparison against the injected ground truth.
5. Remove the “planned” labels in this specification one at a time, and only for commands whose
   milestone evidence now exists. README stays a landing page and links here.

### Final v1 acceptance command set

**Planned until M6 lands.** Run it as a script rather than pasting it: `set -euo pipefail` is what
makes a missing run id stop acceptance instead of silently replaying nothing.

```bash
#!/usr/bin/env bash
set -euo pipefail

EVIDENCE=".artifacts/verification/m6/$(git rev-parse --short HEAD)"
mkdir -p "$EVIDENCE"

cp .env.example .env                    # fill only the M2 owner inputs from §11.3
docker compose up -d --build
docker compose --profile lab --profile obs up -d

# Each source twice: the first delivery creates a ticket, the second must update it.
for SOURCE in grafana datadog pagerduty; do
  docker compose exec -T app smokejumper fixtures replay --source "$SOURCE"
  docker compose exec -T app smokejumper fixtures replay --source "$SOURCE"
done

docker compose exec -T app smokejumper eval | tee "$EVIDENCE/eval-report.txt"

RUN_ID="$(docker compose exec -T app smokejumper runs latest --format id | tr -d '\r')"
test -n "$RUN_ID"
docker compose exec -T app smokejumper replay "$RUN_ID" | tee "$EVIDENCE/replay-$RUN_ID.txt"

docker compose exec -T app alembic current | tee "$EVIDENCE/alembic-head.txt"
docker compose down                     # volumes preserved; `down -v` would destroy them
```

Every `smokejumper` invocation runs inside the deployment because all three need Postgres, and
`postgres` does not resolve on the host. `tr -d '\r'` is defensive: `docker compose exec` appends a
carriage return whenever a TTY is allocated, and a run id carrying one matches no record.

Release proof is more than the transcript. Retain in the M6 evidence directory: `$RUN_ID`, the
create-then-update ticket pair for each of the three sources, the Slack thread timestamp, the audit
file and byte range, `eval-report.txt`, the Phoenix trace id, and the faultbox
expected-vs-actual conclusion comparison. `smokejumper eval` reporting 4/5 with no ticket receipt
is not acceptance.
