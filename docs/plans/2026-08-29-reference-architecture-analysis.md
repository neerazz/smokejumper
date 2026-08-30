# Smokejumper — reference-architecture analysis: what exists, what to reuse, what is ours

Date: 2026-08-29 · Baseline: `d0ed9fe` · Status: RESEARCH RECEIPT + component verdicts. Feeds the
C3 diagram (`architecture/system/c3-components.svg`) and precedes any plan. Every version,
date, license and star count below was read from PyPI JSON or the GitHub API on 2026-08-29 unless
marked INFERRED. Four research lanes; their full reports are summarised, not reproduced.

---

## 0. Verdict

**Of the 27 components on the C3 diagram, 19 have a named reference to adopt or copy; 8 are ours to
build — and those 8 are exactly the ones no shipped product has.** The loop of replan → rebuild
came from designing components that already exist (channel plumbing, dedup, tool contracts, cost
math, retry, scheduling, structured output) instead of the ones that don't (typed
hypothesis/evidence state, evidence snapshots, deterministic replay from recorded tool results,
per-agent budget governor, adversarial verify, no-fault evals, the agent-spec loader, the alert
webhook normalizers).

Three facts change the previous design:

1. **Six MCP servers already exist for the witness ports** — Grafana (Prometheus + Loki + alerting
   + incidents + on-call in one official server), Datadog (official, hosted, 200+ tools),
   Kubernetes (Red Hat, `--read-only`), GitHub (official), Linear (official, hosted), and a
   community Prometheus fallback. The `mcp/servers/` package I drew shrinks to **two things we
   write: inbound alert webhooks and outbound chat interactivity.** Nothing else has an MCP shape
   to reuse, and nothing else needs one.
2. **No Python multi-channel bidirectional chat library is worth adopting** (Apprise is send-only;
   Errbot is GPL; opsdroid stale 16 months; Rasa <3.11; Bot Framework archived; Botkube is Go and
   dormant). The right move is one thin `ChannelAdapter` Protocol over the official SDKs:
   slack-bolt Socket Mode (8 setup steps, 2 credentials, no public URL), discord.py, and
   python-telegram-bot. Botkube's `Message/Section` IR and Robusta's `Blocks` are the reference
   for the channel-neutral rendering layer, so a Finding never formats itself for Slack.
3. **Four of our contract enums diverge from the whole field and should change before code lands
   on them**: `Conclusion.status` mixes verdict with lifecycle (`needs_human`); `Severity.medium`
   exists nowhere else (the middle tier is `warning` in 4 of 6 schemas); `AgentEvent` has no
   `status` (firing/resolved) so a source resolve cannot route through the fingerprint; evidence is
   `list[str]` where the field is typed `{href,text}` with numbered citations.

What the research **confirmed** and should stop being re-litigated: LangGraph + Postgres
checkpointer, prompts in git with sha256 (no surveyed product does this — it is a real edge), JSONL
audit as truth, fingerprint-at-the-edge dedup, the human gate at remediation only.

---

## 1. Rubric and depth plan

Each component was scored on four questions. Depth was set per lane before fetching, not ad hoc:

| Q | Question | Evidence required | Depth reached |
|---|---|---|---|
| 1 | Does a mature reference implement it, with a published decomposition? | repo tree read (directory names), not README prose | 8 OSS repos tree-read; 12 incident/alert data models field-read |
| 2 | Reusable as a Python 3.12 module? | PyPI JSON: version, release date, license, `requires_python`; GitHub: archived flag, last push | 60+ packages checked |
| 3 | How does its internal split compare to ours? | entity names + interface method names quoted | per component below |
| 4 | Verdict + integration depth | adopt (pip) / consume (sidecar or hosted) / copy (design, we write) / build (nothing exists); lines of glue estimated | per component below |

**Not reached (named so it is a search receipt, not a verdict):** Datadog/incident.io/Rootly/
PagerDuty engineering blogs beyond 1–3 pages; Komodor help centre (403); Grafana "inside the
harness" post (403); Opsgenie alert-log fields (429); CISA playbook PDF (403); LiteLLM
`BudgetManager` maintenance status (docs 404, code present); exact PydanticAI version that added
`AgentSpec`. Next probe for each is a browser session, not another fetch.

---

## 2. Reference landscape (repo facts, 2026-08-29)

| Repo | Lang | License | Stars | Latest release | Status | What it is best at |
|---|---|---|---|---|---|---|
| robusta-dev/holmesgpt | Python | Apache-2.0 | 3,164 | 0.40.0 (2026-08-26) | active, CNCF sandbox | tool contract (`Toolset`/`Tool`/`StructuredToolResult`), 46 toolsets, eval corpus (274 fixtures), context caps |
| keephq/keep | Python | MIT + `ee/` | 12,260 | v0.54.2 (2026-07-13) | active | 126 providers, two-tier dedup, CEL correlation, topology; **not pip-installable** (platform) |
| Netflix/dispatch | Python | Apache-2.0 | 6,494 | v20241220 | **archived 2025-09-01** | incident vs case split, 22 typed plugin bases, `Event` timeline entity |
| grafana/oncall | Python | AGPL-3.0 | 3,887 | v1.16.11 (2026-02-11) | **archived 2026-03-24** | templated `grouping_id`/`resolve_condition`, escalation snapshot, per-channel renderer/templater |
| alerta/alerta | Python | Apache-2.0 | 2,528 | v9.1.0 (2026-03-28) | active | natural-key dedup + `correlate[]`, entry-point plugin discovery |
| k8sgpt-ai/k8sgpt | Go | Apache-2.0 | 8,132 | v0.4.37 (2026-08-27) | active | deterministic analyzers emit typed `Failure` first; LLM only explains; `serve` exposes MCP |
| robusta-dev/robusta | Python | MIT | 3,083 | 0.48.0 (2026-08-26) | active, but `<3.12` | `Finding` + `Blocks` IR, 24 sinks, `GroupingParams` storm modes |
| kubeshop/botkube | Go | MIT | 2,304 | v1.14.0 (2024-11-13) | dormant | `Message/Section` IR, interactive-vs-markdown notifier split |
| grafana/mcp-grafana | Go | Apache-2.0 | 3.4k | pushed 2026-08-30 | active, official | Prometheus/Loki/alerting/incident/on-call tools in one MCP server |
| containers/kubernetes-mcp-server | Go | Apache-2.0 | 2.0k | active | official (Red Hat) | pods/events/resources/helm, `--read-only` |
| github/github-mcp-server | Go | MIT | 32.6k | active | official | remote or Docker; toolsets |

Products with fine-grained step reporting (read from docs, feeding §6): Grafana Assistant
Investigations (hypothesis states `open / root cause / symptom / disproven / blocked`, numbered
citation chips, "first three, with a count"), Cleric (activity log rows: planning, tool executions
with raw output, reasoning, plan updates), Datadog Bits (`validated / invalidated / inconclusive`,
Investigation Steps vs Hypothesis Tree), incident.io timeline (pins stamped at original post time),
PagerDuty log entries (17 typed rows with `agent` + `channel`), FireHydrant events (22 types,
`visibility`, `author.source`).

---

## 3. Component-by-component: reference → verdict → what changes on the diagram

Legend: **ADOPT** = pip dependency · **CONSUME** = run/point at an existing server · **COPY** = take
the design, write ~N lines · **BUILD** = nothing exists; ours.

### 3.1 Ingestion

| C3 component | Reference (decomposition read) | Verdict | Library / facts | Glue | Diagram change |
|---|---|---|---|---|---|
| `receiver/routes.py` (5 webhooks) | Alerta `WebhookBase.incoming(path, query, payload) -> Alert` discovered via setuptools entry points; Keep `BaseProvider._format_alert` static per provider | COPY (landed already, keep) | — | 0 | tag "copy Alerta/Keep" |
| `receiver/normalizers/` | **Alertmanager webhook v4** is the de-facto schema (Grafana Alerting emits the same shape — one parser, two sources); Keep `AlertDto` + `AlertSeverity{CRITICAL 5, HIGH 4, WARNING 3, INFO 2, LOW 1}` + `AlertStatus{FIRING, RESOLVED, ACKNOWLEDGED, SUPPRESSED, PENDING, MAINTENANCE}` | COPY schema, BUILD normalizers (there is no library that normalizes vendor webhooks and is importable) | PagerDuty official client `pagerduty` 7.0.0 (2026-07-15) for verification helpers only | ~5 normalizers, landed | `AgentEvent` gains `status`, `severity_number`, `labels`, `links[]` (§4) |
| `receiver/repository.py` dedup | Keep `alert_deduplicator`: fingerprint = sha256(`FINGERPRINT_FIELDS`) then content hash minus `ignore_fields` → **full** (drop) vs **partial** (update) duplicate; Opsgenie "at most one open alert with the same alias"; FireHydrant `idempotency_key` + OPEN/CLOSED pairing | COPY | — | ~60 lines on top of landed `admit()` | dedup scope becomes **open run per fingerprint**, time window = fallback cap; audit `duplicate_reason` |
| `storm_policy.py` | Robusta `GroupingParams{group_by, interval, notification_mode: regular\|summary{by, threaded}}`; OnCall `NOTIFY_IF_NUM_ALERTS_IN_TIME_WINDOW`; Alerta `is_flapping(window=1800s, count=2)` | COPY | — | ~200 lines | rename to `grouping.py`; add `summary` mode (threaded summary table) beside `kind=storm` |
| `queue/` + `worker.py` | Redis Streams direct (ADR-0006); no reference does better for one process | keep | redis 5.2 | 0 | — |

### 3.2 Channels and actions

| C3 component | Reference | Verdict | Library / facts | Glue | Diagram change |
|---|---|---|---|---|---|
| `ChannelAdapter` (Slack) | Botkube `notifier.Bot{SendMessage, SendMessageToAll}` + `Dispatcher` splitting interactive vs markdown notifiers; Dispatch `ConversationPlugin{create, add, send}` | ADOPT SDK + COPY IR | **slack-bolt 1.30.0** (2026-07-15, MIT) `AsyncApp` + `AsyncSocketModeHandler`; slack-sdk 3.44.0; typed Block Kit via slackblocks 2.2.0 (MIT) | ~150 lines | one `channels/` package: `ir.py` (Message/Section IR), `slack.py`, `discord.py`, `telegram.py` |
| `ChannelAdapter` (Discord) | same | ADOPT | **discord.py 2.7.1** (2026-03-03, MIT, 16.2k★) — `ui.View/Button`, `Message.create_thread`; mention-only handling avoids the privileged Message Content intent | ~120 lines | phase 2 |
| `ChannelAdapter` (Telegram) | same | ADOPT (LGPL decision) | **python-telegram-bot 22.8** (2026-06-12, LGPL-3.0, 29.4k★), `message_thread_id` | ~100 lines | phase 2 |
| Teams | Bot Framework **archived 2026-01-05** → Microsoft 365 Agents SDK (`microsoft-agents-hosting-core` 1.5.0, MIT, 209★) | defer | — | — | not on diagram |
| Rendering IR | Robusta `Enrichment{blocks: [BaseBlock]}`; Botkube `Message{Sections[{Header, Body, Buttons, TextFields, BulletLists, Context}], ThreadMessage, ReplaceOriginal}` | COPY | — | ~120 lines | new `channels/ir.py`; Findings never emit Block Kit |
| `TicketingPort` + adapters | Dispatch `TicketPlugin{create, update, delete}`; no unified Python issue-tracker abstraction exists (searched linear-py/linear-sdk/linear-api/pylinear) | COPY interface; CONSUME Linear/GitHub via MCP; ADOPT clients where no MCP | Linear: **official MCP `mcp.linear.app/mcp`** or `gql` 4.0.0; Jira: atlassian-python-api 5.0.4 (2026-08-28, Apache-2.0); GitHub: official MCP or PyGithub 2.10.0 (LGPL); Asana 5.3.0 official; ServiceNow pysnc 1.2.1 | landed port + ~80/adapter | `linear.read` server deleted — consume Linear MCP |
| Slack receipt | Cleric/Claude Tag pattern: one root message edited in place + thread replies for findings/approvals/conclusion only | COPY | — | in `channels/slack.py` | §6 rules |

### 3.3 Intelligence

| C3 component | Reference | Verdict | Library / facts | Glue | Diagram change |
|---|---|---|---|---|---|
| `registry_loader.py` (AgentSpec) | **PydanticAI `AgentSpec`** (2.36.0, 2026-08-29, MIT): `Agent.from_file()` YAML/JSON with `output_schema`/`deps_schema` as JSON Schema and `to_file()` emitting a companion schema for YAML-LS. Adopting it wholesale = two agent runtimes (it builds a PydanticAI Agent, not a LangGraph node). Claude Code subagent frontmatter has the right field vocabulary but no published validator; Skills spec defines skills, not agents | COPY the spec shape | pydantic + pyyaml + python-frontmatter | ~40 lines + exported JSON Schema (the load-bearing part: editor validation stops YAML↔prompt↔schema drift) | keep; note "shape: PydanticAI AgentSpec" |
| `prompt_registry.py` | Langfuse prompts 4.15.1 (MIT self-host; integer versions + labels + prompt↔trace link) vs **git + sha256 (ADR-0020)** | keep git (ADR-0020 stands: no third-party DB owns behaviour); Langfuse allowed as read-side playground only | — | 0 | — |
| `skill_loader.py` | Agent Skills spec (`name, description, license, compatibility, metadata, allowed-tools`; body <5k tokens, <500 lines); `skills-ref` 0.1.1 validator (Apache-2.0, stale 7 months) | ADOPT spec, optional validator | skills-ref 0.1.1 | ~30 lines | tag "spec: agentskills.io" |
| `schema_validator.py` / structured output | LangChain `response_format=ToolStrategy\|ProviderStrategy` with `handle_errors` re-ask (langchain-core 1.6.1, MIT); instructor 1.16.0 for standalone extraction | ADOPT | langchain-core 1.6.1 | 0 beyond pydantic models | merge into agent runner; component stays as the schemas dir |
| `agent_runner.py` loop | HolmesGPT `holmes/core`: `safeguards.prevent_overly_repeated_tool_call`, `truncation/`, `transformers/llm_summarize` (tool output capped at 15% of context / 25k tokens with disk spill), `conversation_history_compaction` prompt | COPY the three safeguards; LangGraph node stays ours | — | ~120 lines | add "safeguards: repeat-call block · output cap · compaction" |
| `hypothesis_board.py` | **No library.** Grafana hypothesis states; AgentRCA paper is method only. LangGraph `StateGraph` accepts pydantic state (input validation only; not `create_agent`) | BUILD | pydantic in LangGraph state | ~100 lines | stays BUILD — this is ours |
| Supervisor nodes / workflows | LangGraph 1.2.11 + langgraph-checkpoint-postgres 3.1.2 (MIT). **Critical fact:** time-travel *re-executes* nodes; only `@task` results are restored from the checkpointer → every LLM and tool call must be wrapped in `@task` or replay is fiction | ADOPT (already decided) | — | discipline, not code | add "every llm/tool call = @task" |
| `eval_runner.py` | **HolmesGPT `tests/llm`**: `test_case.yaml{user_prompt, expected_output[], tags regression/easy/medium/hard, before_test/after_test}`, mock mode replays recorded tool files vs `RUN_LIVE=true`, `CLASSIFIER_MODEL` judge 0/1, `ITERATIONS=10`, results by tag×model, committed history. Scorers: **Inspect AI 0.3.260** (MIT, UK AISI) `model_graded_fact`, per-metadata grouping → per-agent hit rate; runner-up pydantic-evals 2.36.0 | COPY harness pattern + ADOPT Inspect scorers | inspect-ai 0.3.260 | ~300 lines | tag "pattern: HolmesGPT tests/llm · scorers: Inspect AI" |

### 3.4 Tools, witnesses, governance

| C3 component | Reference | Verdict | Library / facts | Glue | Diagram change |
|---|---|---|---|---|---|
| Tool contract | HolmesGPT `Toolset{name, enabled, prerequisites[Static\|Callable\|Command\|Environment], tools, llm_instructions, transformers}` · `Tool{name, description, parameters, _invoke() -> StructuredToolResult{schema_version, status, error, return_code, data, url, invocation, params, elapsed_seconds}}`; YAML toolsets; MCP servers as a toolset type. `pip install holmesgpt` 0.40.0 works on 3.12 but drags litellm-pinned, supabase, kubernetes, kafka, boto3 | COPY the contract (importing the package for one module is not worth ~15 heavy deps) | — | ~150 lines | `ToolResult` gains `invocation`, `params`, `elapsed_ms`, `status`; **prerequisite check separated from invocation** |
| `mcp/gateway.py` | langchain-mcp-adapters 0.3.2 `MultiServerMCPClient` (no interceptor hooks); governance one layer up via LangChain `wrap_tool_call` middleware ("called zero times (short-circuit), once, or multiple times (retry)"); FastMCP 3.4.7 middleware is server-side only; agentgateway (Rust, LF, CEL RBAC, OTel) when a network boundary is wanted | ADOPT adapters + middleware | langchain-mcp-adapters 0.3.2, fastmcp 3.4.7 for the two servers we write | ~60 lines tier/allowlist/audit | "two checks" stays: middleware (ours) + executor re-check |
| `mcp/servers/*` (6 planned) | **CONSUME**: grafana/mcp-grafana (`query_prometheus`, `query_loki_logs`, `query_loki_patterns`, `list_incidents`, `get_current_oncall_users`, `--disable-<cat>`), Datadog MCP (hosted, `?toolsets=`, 50 calls/10s, 50k/month quota), kubernetes-mcp-server `--read-only`, github-mcp-server, Linear MCP (OAuth 2.1 or API key, read-only endpoint variant), pab1it0/prometheus-mcp-server as no-Grafana fallback | CONSUME 6; WRITE 2 | — | config per server | **delete** `metric.query`, `log.search`, `linear.read` servers from the diagram; keep `knowledge.search`, `recipe.read`, `change.list` (no external MCP has our recipes/episodes), and the two we must write: webhook receiver tools (if exposed) and channel interactivity tools |
| Witness ports (8) | Keep `BaseProvider` (`PROVIDER_SCOPES`, `validate_scopes`, `_query`) as the adapter shape; k8sgpt analyzers as the deterministic pre-analysis idea | COPY shape; CONSUME k8sgpt `serve` (gRPC/MCP) as a deterministic pre-analyzer sidecar for K8s packs | k8sgpt sidecar | thin | witness ports become **"MCP server bindings"**; only `ChatSource` and `IncidentHistorySource` are in-process |
| Approvals broker (B5) | HolmesGPT `ApprovalRequirement{needs_approval, reason}` / `ToolApprovalDecision{save_prefixes}` (remembered approvals); Dispatch `SignalEngagement{require_mfa}`; LangGraph `interrupt()`/`Command(resume=)` | COPY shapes on LangGraph interrupt | — | landed design | add "remembered approvals by prefix" |
| Budget / ledger | LangChain `ModelCallLimitMiddleware(thread_limit, run_limit)` + `ToolCallLimitMiddleware` (counts); **litellm `completion_cost()`** over the community price JSON (1.98.0, MIT); `BudgetManager` docs 404 — do not use; tokencost stale; OTel gen_ai has no cost attribute (OpenLLMetry #1042 open since 2024) | ADOPT counts + cost table; BUILD the USD budget node | litellm (for `completion_cost` only) | ~30 lines | governor per agent file stays BUILD |
| Circuit breaker / retry | tenacity 9.1.4 (Apache-2.0, async); breaker: pybreaker async = Tornado only, aiobreaker dead (2021), **purgatory 3.0.1** (MIT, asyncio, Redis state) 22 months without release | ADOPT tenacity; breaker: purgatory or ~40 lines | tenacity 9.1.4 | ~40 | — |
| Scheduler | **APScheduler 3.11.3** (2026-06-28, MIT) — 4.0 still alpha "do NOT use in production"; arq maintenance-only since 2025-10; DBOS 2.31.0 (MIT, Postgres-durable cron, exactly-once) as the durable runner-up | ADOPT APScheduler 3.x | apscheduler 3.11.3 | config | — |

### 3.5 Recorder, replay, evidence

| C3 component | Reference | Verdict | Library / facts | Glue | Diagram change |
|---|---|---|---|---|---|
| `recorder/writer.py` (JSONL) | Dispatch `Event{uuid, started_at, ended_at, source, description, details, type, owner, pinned}`; OnCall `AlertGroupLogRecord`; FireHydrant `IncidentEvent{type(22), occurred_at, visibility, author{source}}` | keep (landed); COPY fields | — | ~20 | `AuditEvent` gains `occurred_at`, `visibility`, `pinned`, `refs{hypothesis_id, evidence_ids, tool_call_seq}` |
| Timeline / step ledger | incident.io: Activity Log is the source, Timeline is a curated projection | COPY | — | projection query | "TimelineEntry is a projection of B8, never a second log" |
| `evidence_snapshot.py` | **No product stores snapshots** — citations are deep links that die with vendor retention (13/14). HolmesGPT `StructuredToolResult{invocation, params}` is the closest recorded unit | BUILD | content-addressed files beside JSONL | ~80 | stays BUILD — ours |
| `replay.py` | LangGraph `@task` restore; **vcrpy 8.3.0** (MIT, httpx/aiohttp) for LLM HTTP replay in tests; litellm cache as alternative | ADOPT vcrpy for tests + BUILD ~80-line tool-result cache that re-injects recorded `ToolResult`s into `@task` | vcrpy 8.3.0 | ~80 | tag "vcrpy + @task" |
| Traces | OpenInference (`openinference-instrumentation-langchain` 0.1.73) → Phoenix (ELv2) or Langfuse (MIT) | ADOPT (ADR-0019 stands) | — | config | — |

---

## 4. Contract corrections (from 12 data models read field-by-field)

| Contract | Divergence | Field majority | Change |
|---|---|---|---|
| B2 `AgentEvent` | no `status` | Keep/PD/OnCall/Alerta all route resolve/ack through the dedup key | add `status ∈ {firing, acknowledged, resolved, suppressed}` default `firing` |
| B2 `Severity` | `medium`, `high` | PD `critical/warning/error/info`; Keep `critical/high/warning/info/low`; FH `FATAL/ERROR/WARN/INFO`; OTel 1–24 numeric | `medium → warning`; add `severity_number` (OTel) so per-source maps are data; keep priority a separate axis (Opsgenie P1–P5, PD urgency) |
| B2 dedup | fixed 15-min window | "at most one open alert with the same alias" (Opsgenie); FH 24h-or-CLOSED; Keep full vs partial | scope to open run per fingerprint; window is a cap; audit `duplicate_reason` |
| B6 `Conclusion.status` | verdict + lifecycle mixed | every product separates them | `verdict ∈ {root_caused, mitigated, inconclusive, not_actionable}` + run `status ∈ {triage, investigating, waiting_human, mitigated, resolved, closed}`; `not_actionable` covers Dispatch `benign/false_positive/user_acknowledged` |
| B11 `Finding.hypothesis: str` | untyped | Grafana `open/root cause/symptom/disproven/blocked`; Datadog `validated/invalidated/inconclusive` | promote `Hypothesis{id, statement, status, confidence, evidence_ids[], agent, created_seq, updated_seq}`; Finding becomes an observation linked to hypotheses |
| evidence `list[str]` everywhere | untyped | PD/FH `links[{href,text}]`; OCSF `finding_info{src_url, data_sources}`; Grafana numbered chips | `Evidence{id E1.., kind ∈ {log, metric, trace, deploy, config, code, doc, chat, knowledge}, title, href, excerpt, captured_at, tool_call_seq, source_ref}` |
| B8 `AuditEvent` | missing projection fields | FH/Rootly/Dispatch | add `occurred_at`, `visibility`, `pinned`, `refs` |
| B4 `ToolResult` | no invocation record | HolmesGPT `StructuredToolResult` | add `seq`, `invocation`, `params`, `elapsed_ms`, `status` |
| `proposed_actions: list[str]` | untyped | Dispatch Task, incident.io follow-up | `Action{id, kind ∈ {tool, ticket, notify, followup}, tier, status ∈ {proposed, awaiting_approval, approved, denied, executed, failed, expired}, …}` linked to B5 |

Where ours is *ahead* of the field (keep): `occurred_at/received_at` pair (OTel-correct);
fingerprint over `(source, source_event_key, entities)`; `prompt_ref + prompt_sha256` on every
`llm_call` — none of the 14 surveyed products records prompt identity.

---

## 5. End-user setup cost (the "easy to connect" requirement, measured)

| Channel | Library | Steps | Credentials | Public URL? | Caveat |
|---|---|---|---|---|---|
| Slack | slack-bolt Socket Mode | 8 (app from our `manifest.json` → app-level token with `connections:write` → install → bot token → 2 env vars → run) | 2 (`xapp-`, `xoxb-`) | **no** | max 10 socket connections; cannot list in public Slack Marketplace |
| Discord | discord.py | 7 + 7 (application → bot token → OAuth URL generator → invite) | 1 | no | mention-only handling avoids the privileged Message Content intent and >100-guild verification |
| Telegram | python-telegram-bot | 3 (BotFather token → env → run, polling) | 1 | no (polling) | LGPL-3.0 — fine when imported, not vendored; needs Neeraj's yes |
| Teams | Microsoft 365 Agents SDK | — | — | yes | deferred |

Alert sources: Alertmanager/Grafana share one parser (v4 shape); Datadog, PagerDuty, generic
already landed; Opsgenie and Sentry would be raw-webhook normalizers (their SDKs are for emitting,
not ingesting).

---

## 6. Step-level reporting — the converged UX and our ledger row

Convergent pattern across Grafana Assistant, Cleric, Datadog Bits, Claude Tag, Claude Code,
Devin: **one mutable summary card** (checklist + hypothesis cards) **+ an append-only activity
log collapsed by default + numbered evidence citations + an explicit `inconclusive` terminal with
partial findings + a human verdict affordance** ("Was this the cause?").

Ledger row (one row = one B8 projection):

```
StepRow{ run_id, seq, ts, occurred_at,
  phase: detect|triage|investigate|verify|mitigate|close,
  row_type: status|tool_call|evidence|finding|hypothesis|approval|action|note|conclusion,
  state: pending|running|done|failed|skipped|waiting_human,
  actor{id, kind: agent|human|system}, title ≤130, detail_md (collapsed),
  evidence_ids[], hypothesis_id?, hypothesis_status?, confidence?,
  links[{href,text}], visibility: internal|external, pinned }
```

Slack rendering rules: one root message per run edited in place (checklist of phases +
hypothesis cards with status emoji); thread replies only for `finding`, `hypothesis` state change,
`approval`, `conclusion`, and human questions; `tool_call`/`evidence` roll up into a counter ("14
tool calls · 6 sources") with a "View steps" link to the full B8 transcript (Grafana's "first
three, with a count of the total"); `conclusion` always carries verdict + top hypothesis with
`Source N` chips and, when inconclusive, a "Partial findings" block (Cleric); approval rows carry
buttons and expire to `failed(expired)`.

---

## 7. What is genuinely ours (the 8 BUILD items) — and why that is the product

| BUILD | Field status | Why nobody has it |
|---|---|---|
| Typed hypothesis board in graph state | 0 libraries | products have it as UI state, not as a reusable typed contract |
| `EvidenceRecord` snapshots (content-addressed) | 13/14 deep-link only | retention economics; nobody wanted to store query results |
| Deterministic replay from recorded tool results (`@task` + cache) | 12/14 | LangGraph replay re-executes; vendors keep only traces |
| Per-agent-file budget governor with USD ledger | 12/14 no published governor | vendors bill credits; OSS agents count calls, not dollars |
| Adversarial verify gate on `root_caused` | 5/14 have a verifier | it costs tokens and lowers headline accuracy |
| No-fault eval cases as a CI gate | 12/14 | AIOpsLab: one agent passed the no-fault case |
| Agent-spec loader with exported JSON Schema (40 lines, PydanticAI shape) | spec exists, LangGraph loader doesn't | PydanticAI's builds its own runtime |
| Alert webhook normalizers (Datadog, PagerDuty, Opsgenie, Sentry) | Keep has 126 but is a platform | nobody ships them as an importable library |

Everything else on the diagram is adopt, consume or copy. That is the difference between this
document and the two before it.

---

## 8. Decisions only Neeraj can make

1. **LGPL acceptance** for python-telegram-bot and PyGithub (fine when imported). No → Telegram to
   phase 2, GitHub via MCP only.
2. **Keep as a sidecar or Keep as a design source.** Sidecar buys 126 providers + CEL correlation
   + topology on day one at the cost of Postgres/MySQL + Redis + a Next.js UI in compose. Copy
   buys ~200 lines and no footprint. Recommendation: copy; revisit if a third alert source lands.
3. **Prompts: keep ADR-0020 (git) or move to Langfuse.** Recommendation: keep git; Langfuse only
   as playground. The sha256-on-every-call edge is worth more than label-based promotion.
4. **HolmesGPT tool contract: import the package or copy the three classes.** Recommendation:
   copy (~150 lines) — importing drags litellm-pinned, supabase, kafka, boto3.
5. **Datadog MCP quota** (50 calls/10s, 50k/month) is a hard ceiling on Datadog-sourced packs;
   accept, or keep `datadog-api-client[async]` 2.59.0 as the witness adapter for that source.
6. **Contract renames in §4** — each is a breaking change to landed code; approve as a set before
   M2, not one at a time later.

---

## 9. Lane receipts

Four lanes, ~580k subagent tokens, 289 tool calls total; every version/date from PyPI JSON or
GitHub API on 2026-08-29; every decomposition from a tree read, not a README. Open items are in
§1. Product step-flow detail for Grafana/Cleric/Datadog was fetched directly from their docs in
this session; the other five products' flows come from the earlier survey.
