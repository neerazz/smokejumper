# Smokejumper — v1 Build Specification

> Level-2 design: everything an implementer (human or agent) needs to build v1 without
> re-asking architectural questions. The level-1 container view is the
> [component diagram](architecture/smokejumper-components.svg); this document refines it into
> contracts, component behavior, flows, data, and verifiable milestones.
>
> **Status: design complete; implementation not started. Reviewed 2026-07-10; architecture
> updated 2026-07-25.** The five open decisions were resolved by Neeraj (see §10); no
> unresolved `⚑` remain. The 2026-07-25 pass added the local observability stack (§2c),
> per-environment configuration (§2d), consolidated MCP into one domain (§5.5), OTel/Phoenix,
> and the prompt registry—decisions 11–15. Every significant decision is recorded with its
> alternatives and accepted trade-offs in [docs/adr/](docs/adr/README.md).

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
| Persistence | SQLAlchemy 2 async + psycopg 3 + Alembic over **one Postgres 16** + pgvector | application state, vectors, graph edges, checkpoints, and the JSONL run/file-offset index share one DB; audit events themselves stay in JSONL |
| Knowledge graph | Postgres edge tables, bi-temporal (valid_at / recorded_at, Graphiti-style) | facts change; never lose what we believed at decision time |
| Memory extraction | LangMem-style extraction in Distiller; **distill, don't append** | append-everything degrades retrieval |
| LLM | **Swappable by config, zero code**: `ModelProvider` port over LangChain `init_chat_model` provider strings (`anthropic:*`, `openai:*`, `google_genai:*`, `ollama:*`, …), configured **per role** (`worker`, `synthesis`) through `config/<env>.yaml` or env overrides. Ships with Anthropic defaults (claude-sonnet-5 workers, claude-opus-4-8 synthesis); switching to Codex/GPT, Gemini, or a local model is an edit to two config values | hard requirement: any provider, swappable at any time; no provider import outside `ports/model.py` |
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
| Eval | Hand-written deterministic scorer over recorded cases: exact B6 status + required evidence refs; no LLM-as-judge in CI | the v1 acceptance metric is small and deterministic; add an eval library only when a non-trivial metric requires it |
| Observability | OpenTelemetry + OpenInference instrumentation; optional `obs` profile runs Phoenix as the default read-side UI, with Langfuse as an exporter-only swap. JSONL remains authoritative | no runtime dependency on the UI; ADR-0019 amends the earlier UI deferral |
| Ticketing SDKs | `githubkit` (MIT, async — over PyGithub: LGPL + "seeking maintainers") · `atlassian-python-api` · official `asana` | TicketingPort (verified: no OSS unifier covers Linear+GitHub+Jira+Asana — ticketutil has the wrong provider set) + **Linear adapter via direct GraphQL** (no official Python SDK; community `linear-api` stale) |

## 2c. Local observability stack (`local` environment only, via compose profiles)

> **Implementation status:** the commands and service names in §§2c–2e are the locked target
> interface, not a claim that the files already exist. They become runnable at M0 (core), M1
> (`lab`/`fixtures`), and M6 (`obs`) respectively.

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
(the original LLM-trace UI deferral, later amended by decision §10.14) — that concerns *our*
audit record; this concerns *the systems Smokejumper observes*.

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
| Ports (§5.10) | stubs allowed | stubs warn | **security-relevant stubs forbidden** |

### Environment-gated safety rules (enforced at boot, not documented-and-hoped)
- **`prod` refuses to start if any security-relevant port is a stub** (`AllowAll`, `NoopGovernance`,
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
├── scripts/check_doc_contract.py # enforces SPEC-only normative documentation
├── fixtures/webhooks/          # golden per-source payloads (§8) + replayer corpus (§2c)
├── tests/                      # unit + contract + replay tests; doc-contract gate exists now
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

| Port | v1 implementation | Local/test substitute | Prod gate |
|---|---|---|---|
| `AuthPort` | host-supplied credential/signature verifier | `AllowAll` | `AllowAll` forbidden |
| `GovernancePort` | host-supplied policy identity | `NoopGovernance` | `NoopGovernance` forbidden |
| `TenancyPort` | `SingleTenant` | same | allowed: single tenancy is the v1 contract, not a stub |
| `ModelProvider` | configured LLM adapter | recorded/fake model | fake forbidden |
| `PlatformPort` | host-supplied platform adapter | `FixturePlatform` | fixture forbidden |
| `ChannelAdapter` | Slack Socket Mode | fake channel | fake forbidden when enabled |
| `TicketingPort` | Linear GraphQL | dry-run/fixture adapter | fixture forbidden when enabled |
| `MemoryPort` | Postgres+pgvector bi-temporal store | in-memory test adapter | in-memory forbidden |

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
retrieve (bundle: 2 similar past cases + 1 recipe) → plan selects specialists → parallel
Assignments → Findings back → aggregate → synthesize Conclusion(root_caused, 0.82) →
Actions: create Linear ticket SMOKE-123 + Slack receipt with evidence links → recorder has
the full trace → run closed.

### 6.2 Approval round-trip (v1 test/demo path)
The production privileged tier is empty. The test-only `demo_destructive_noop` proves the full
path: sub-agent requests privileged tool → MCP gateway suspends run (LangGraph interrupt persisted) →
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
- **Acceptance (v1 exit):** docker-compose up + seeded fixtures; firing the named acceptance
  trio—Grafana, Datadog, and PagerDuty—yields: 1 ticket with correct create-vs-update behavior, Slack receipt, full
  recorder trace, `smokejumper eval` ≥ 4/5 cases matching expected Conclusion status.

## 9. Milestones (each independently verifiable)

| # | Deliverable | Exit check |
|---|---|---|
| M0 | Repo skeleton, contracts, CI, docker-compose (default profile), `config/` layering (§2d), stub ports | `pytest` green; compose boots; `SMOKEJUMPER_ENV=prod` fails closed on stub ports |
| M1 | Receiver + queue + recorder core + `lab`/`fixtures` profiles (§2c) | golden webhooks → normalized events in DB, storm test passes; a real Grafana/Alertmanager alert reaches the queue |
| M2 | Supervisor + ONE specialist + Actions (ticket+receipt) | `evals/case-01.json` traverses queue → Metrics Analyst → B6 → fixture ticket/receipt exactly once; credentialed Linear/Slack is a release smoke test |
| M3 | Knowledge façade (vectors+graph+recipes) wired into retrieve | bundle appears in trace; precedent case cited |
| M4 | Parallel specialists + budgets + Governor | 3 agents in parallel; budget-breach test passes |
| M5 | MCP tiers + approval round-trip | demo noop tool gated end-to-end in test; federated descriptor loads through the same manifest |
| M6 | Replay/eval harness + Distiller CLI + `obs` profile (§2e) + docs | acceptance suite green; the canonical quickstart in this specification works; a run's spans land in Phoenix |

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
10. **Original observability decision (amended by 14)** — JSONL stays the audit source of
    truth. The original platform/UI deferral was later narrowed: decision 14 permits the
    optional Phoenix read-side while preserving this source-of-truth rule.

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
| Disk | at least 10 GiB free for images, volumes, logs, and eval fixtures | M0 | `df -h .` |
| Node + npx | only for regenerating the Mermaid SVG; not an app runtime dependency | docs only | `node --version && npx --version` |

The application container listens on `8000` and exposes `GET /healthz`. Compose service names
and container ports are stable; host ports are overridable so a developer does not have to
kill unrelated local services:

| Service | Container port | Default host port | Local override |
|---|---:|---:|---|
| app | 8000 | 8000 | `APP_HOST_PORT` |
| postgres | 5432 | 5432 | `POSTGRES_HOST_PORT` |
| redis | 6379 | 6379 | `REDIS_HOST_PORT` |
| prometheus | 9090 | 9090 | `PROMETHEUS_HOST_PORT` |
| alertmanager | 9093 | 9093 | `ALERTMANAGER_HOST_PORT` |
| grafana | 3000 | 3000 | `GRAFANA_HOST_PORT` |
| loki | 3100 | 3100 | `LOKI_HOST_PORT` |
| faultbox | 8080 | 8080 | `FAULTBOX_HOST_PORT` |
| phoenix UI | 6006 | 6006 | `PHOENIX_HOST_PORT` |
| OTLP gRPC | 4317 | 4317 | `OTLP_GRPC_HOST_PORT` |

Host-port overrides belong in the untracked local `.env`; service-to-service URLs always use
the stable Compose service name and container port. `.env.example` contains names and safe
defaults only—never tokens.

### 11.2 Accounts, credentials, and identifiers

Secret values are injected at runtime and are never committed. Tests use fakes or fixture
secrets. A missing optional integration disables that adapter; a missing credential for an
enabled adapter fails boot with the variable name, never during an incident.

| Input | Exact configuration surface | Needed by | Owner action / local fallback |
|---|---|---:|---|
| One LLM provider | Standard provider key such as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`; role strings in `SMOKEJUMPER__MODEL__WORKER` and `SMOKEJUMPER__MODEL__SYNTHESIS` | M2 | Choose one live provider. Tests use recorded responses; a local Ollama role is allowed. |
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

### 11.3 Owner checklist—the only inputs an agent cannot manufacture

- [ ] **By M2:** choose the live LLM provider and exact worker/synthesis model strings; provide
  one provider key through the runtime environment and confirm the local spend ceiling.
- [ ] **By M2:** create the Slack app, enable Socket Mode + interactivity, apply the four bot
  scopes above, install it, invite it to the development channel, and provide the two tokens
  plus channel ID through the runtime environment.
- [ ] **By M2:** choose the Linear development team; provide a personal API key and team UUID.
- [ ] **Only for dev/prod:** provide managed Postgres/Redis, read-only Prometheus/Loki, live
  webhook secrets/allowlists, and the real implementations selected for security-relevant
  ports.

Datadog and PagerDuty accounts, public tunnels, a production secret manager, real privileged
tools, and a federated MCP server are **not prerequisites for local v1 acceptance**.

### 11.4 Defaults locked for implementation

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

Implementation is seven milestone PRs in the strict M0→M6 order. Every work packet uses the
same loop: **write one behavioral test → run it and observe the expected failure → implement
the minimum → run the focused test → run milestone gates → commit**. Source-bound framework
calls are checked against current official documentation before code is written; URLs and
non-obvious lifecycle constraints go in the implementing module's docstring or ADR reference.

### Universal gates and evidence

Run after every packet that changes Python; all must exit 0 before its commit:

```bash
uv run pytest -q
uv run ruff check .
uv run pyright
git diff --check
```

Compose-changing packets additionally run `docker compose config`; profile packets run the
specific profile health check. Each milestone receipt records: commit SHA, changed paths,
focused RED/GREEN test, full gate output, runtime probe, and any disabled external adapter.

### M0—foundation, contracts, configuration, and core runtime

**M0.1 · Package and CI skeleton**
- Create: `pyproject.toml`, `uv.lock`, `Dockerfile`, `.dockerignore`, `.gitignore`,
  `src/smokejumper/__init__.py`, `src/smokejumper/cli.py`, `tests/test_package.py`,
  `.github/workflows/ci.yml`; wire the existing `scripts/check_doc_contract.py` and
  `tests/test_doc_contract.py` into CI.
- RED: package import and `smokejumper --help` tests fail because the package does not exist.
- GREEN: src-layout package installs through uv; CI runs pytest, ruff, pyright, and the
  documentation-contract gate on Python 3.12. Commit: `chore: scaffold Python package and CI`.

**M0.2 · One validated settings object**
- Create: `src/smokejumper/config.py`, `config/base.yaml`, `config/local.yaml`,
  `config/dev.yaml`, `config/prod.yaml`, `.env.example`, `tests/test_config.py`.
- RED: precedence tests cover defaults < base < env file < env vars < CLI; malformed config,
  prod stubs, prod missing ceiling, and non-local lab profiles all fail boot.
- GREEN: implement pydantic-settings custom sources and one startup validator. Commit:
  `feat: add layered fail-closed configuration`.

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
- GREEN: protocols/ABCs plus smallest stubs only. Commit: `feat: add environment-gated ports`.

**M0.5 · App, database migrations, and default Compose stack**
- Create: `src/smokejumper/app.py`, `src/smokejumper/db.py`, `alembic.ini`, `migrations/`,
  `docker-compose.yml`, `tests/test_health.py`.
- RED: `/healthz` and database readiness fail before app/services exist.
- GREEN: app + Postgres 16/pgvector + Redis start with health checks; schema migration table
  exists; app reports dependency health without leaking credentials. Commit:
  `feat: boot core compose stack`.

**M0 exit evidence**
```bash
uv run pytest -q
uv run ruff check .
uv run pyright
docker compose config
docker compose up -d --build
curl --fail http://localhost:${APP_HOST_PORT:-8000}/healthz
docker compose run --rm \
  -e SMOKEJUMPER_ENV=prod \
  -e SMOKEJUMPER__BUDGET__MAX_USD_PER_RUN= \
  app smokejumper check-config  # expected non-zero: stubs + ceiling
docker compose down -v
```

### M1—recorder, receiver, queue, and local incident lab

1. **Recorder first:** create `recorder/writer.py`, `recorder/broadcast.py`, runs-index
   migration, and tests for append-only JSONL, monotonic per-run `seq`, process-unique files,
   byte offsets, failure counter, and `logs --follow`.
2. **Inbound persistence:** add events/quarantine migration and repository; test 401+audit for
   unverifiable payloads and 202+quarantine for unparseable payloads.
3. **Normalizers:** implement generic, Grafana, Datadog, PagerDuty, and Alertmanager adapters
   from `fixtures/webhooks/`; each source gets golden valid/invalid/signature/severity tests.
4. **Fingerprint/dedupe/storm:** test canonical entity ordering, stable hash, 15-minute dedupe,
   20-vs-21 fingerprint boundary, five-minute reset, and one `kind=storm` enqueue.
5. **Redis Streams:** create producer/consumer group, at-least-once reclaim, event-id
   idempotency, and max-in-flight=3 tests.
6. **Lab + fixtures profiles:** create `compose/{prometheus,alertmanager,grafana,loki,faultbox}/`,
   replayer, provisioning, and health probes. A real Alertmanager/Grafana alert must reach the
   Redis stream; Datadog/PagerDuty fixtures require no SaaS account.

Commit each numbered packet separately. M1 exits only when the focused storm test and the real
lab alert receipt are both retained as evidence.

### M2—one complete intelligence-to-action path

1. **Prompt + registry seed:** create immutable `prompts/supervisor/{plan,synthesize}/v1.md`,
   `prompts/agents/metrics-analyst/v1.md`, `prompts/CHANGELOG.md`, and
   `registry/agents/metrics-analyst.yaml`; validate prompt refs and hashes at boot.
2. **ModelProvider:** implement the LangChain `init_chat_model` seam only in
   `ports/model.py`; record model, prompt ref/hash, response, usage, latency, and cost. Tests
   use a fake provider and recorded responses before any live call.
3. **Single-specialist graph:** implement intake→retrieve(empty bundle)→plan→dispatch one
   Metrics Analyst→aggregate→synthesize B6 with Postgres checkpointing and restart test.
4. **Slack adapter:** implement async Bolt Socket Mode mention listener, thread receipts, and
   button callback plumbing behind `ChannelAdapter`; contract tests use fake Slack clients.
5. **Linear + Actions:** implement provider-neutral TicketingPort conformance tests, direct
   GraphQL adapter, fingerprint lookup, create-vs-update, and `(fingerprint, run_id)`
   idempotency. Always inspect GraphQL `errors` even on HTTP 200.
6. **Golden end-to-end:** one fixture alert produces one recorded run, one B6 Conclusion, one
   Linear issue, and one Slack receipt; replaying the delivery updates rather than duplicates.

M2 cannot claim live completion until the three owner inputs in §11.3 exist. All earlier
packets remain buildable with fakes.

### M3—local knowledge and GraphRAG retrieval

1. Add migrations for `episodes`, `kg_nodes`, and `kg_edges` with pgvector and bi-temporal
   constraints; test current-time and as-believed-at-time queries.
2. Implement `MemoryPort` Postgres adapter: episode similarity, ≤2-hop graph expansion, and
   deterministic invalidation without deleting historical belief.
3. Implement recipe loading/validation from `recipes/*.yaml` and trigger-tag matching.
4. Compose `retrieve()` under a token/item budget into B3 with source refs and scores; the
   federated list is empty through a governed stub until M5—Knowledge never opens an MCP
   connection itself.
5. Re-run M2 golden case seeded with two episodes + one recipe; B6 must cite the returned
   source refs and the recorder must contain the exact bundle.

### M4—parallel specialists, budgets, and Governor

1. Add immutable prompts + registry entries for Log Analyst and Change Auditor; keep DB/Code/
   Precedent agents present but disabled. Validate tool allowlists and budget fields.
2. Dispatch three B11 Assignments concurrently and aggregate findings in registry-stable order;
   prove parallelism with a barrier test, not wall-clock guessing.
3. Add call-count middleware plus the hand-written token/USD ledger; breach must synthesize an
   `inconclusive` B6 with partial findings.
4. Implement provider circuit breaker, max in-flight, queue-depth storm brake, and tests at
   every threshold boundary.
5. Add APScheduler jobs for registry sync and approval expiry; scheduled investigations remain
   recipe-driven and produce normal B2 events.

### M5—single MCP governance seam and approval round-trip

1. Create `mcp/manifest.yaml` schema and loader; boot fails for unknown tools, duplicate names,
   absent tiers, or registry tools missing from the central manifest.
2. Implement FastMCP gateway middleware and a separate executor-tier check; test that bypassing
   either one alone still cannot execute a privileged tool.
3. Implement in-process read servers for Prometheus metrics, Loki logs, knowledge search/
   expansion, Linear read, recipe read, and fixture platform assets with bounded query shapes.
4. Add `demo_destructive_noop` only under test configuration; production privileged manifest
   remains empty.
5. Implement opaque approval-token mint/consume, 30-minute expiry, Slack buttons, LangGraph
   interrupt/resume, restart durability, deny, expiry, replay, and double-click race tests.
6. Implement federated descriptors and loader through the same gateway; prove a descriptor
   cannot import a tool absent from the central manifest or widen its tier.

### M6—replay, eval, Distiller, traces, and release proof

1. Implement deterministic `replay <run_id>` from JSONL + runs index with recorded model/tool
   outputs, then live eval mode as an explicit opt-in.
2. Add five `evals/*.json` cases and `smokejumper eval`; CI requires deterministic ≥4/5 and
   reports per-agent hit rate without calling a live model.
3. Implement manual Distiller CLI: episode and graph candidates commit transactionally; recipe
   candidates land only in `recipes/drafts/` for human promotion.
4. Add OpenTelemetry/OpenInference instrumentation only at ModelProvider and MCP gateway;
   configure Phoenix under `obs`; verify JSONL remains complete with Phoenix stopped.
5. Run the faultbox release case from injected fault through alert, parallel investigation,
   grounded B6, one Linear ticket, Slack receipt, JSONL replay, and matching ground truth.
6. Replace any remaining “planned” labels in this specification only after their commands work;
   README stays a landing page and links here rather than copying the quickstart.

### Final v1 acceptance command set

These commands are **planned until M6 lands**. At release they become the canonical quickstart
and must be executed exactly as written before the status changes from design to implemented:

```bash
cp .env.example .env                    # fill only the M2 owner inputs from §11.3
docker compose up -d --build
docker compose --profile lab --profile fixtures --profile obs up -d
uv run smokejumper fixtures replay --source grafana
uv run smokejumper eval                 # expected: at least 4/5 deterministic cases match
uv run smokejumper replay <run_id>      # expected: same B6 with recorded model/tool outputs
```

Release proof is not the command transcript alone: retain the run ID, one-ticket idempotency
receipt, Slack thread timestamp, audit file + byte range, eval report, Phoenix trace ID, and
the faultbox expected-vs-actual conclusion comparison.
