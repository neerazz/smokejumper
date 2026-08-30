# Smokejumper v1 — completion assessment and atomic build plan

Date: 2026-08-29 · Baseline commit: `d0ed9fe` · Status: PLAN ONLY, nothing below is built.

This document is a plan and a measurement. `SPEC.md` stays the only normative source; where
this file and SPEC disagree, SPEC wins and this file is stale.

---

## 1. Verdict: about 25% of v1 is built, and the 25% is the deterministic plumbing

Measured against SPEC §12's 39 work packets (M0: 5, M1: 7, M2: 6, M3: 5, M4: 5, M5: 6, M6: 5):

| Milestone | Packets | Landed | Evidence |
|---|---|---|---|
| M0 foundation | 5 | 5 | 331 unit/contract/architecture tests green on `d0ed9fe` (`uv run pytest tests/unit tests/contracts tests/architecture`); `/healthz`, alembic 0001–0004, fail-closed `prod` |
| M1 receiver/queue/recorder | 7 | 4.5 | five HTTP normalizers, dedupe under 25-way concurrency, Postgres→Redis outbox, worker, fixture ticket, `GET /runs/{fp}`. Missing: storm coalescing, exact-B1 audit for rejected/quarantined, `lab` profile, `fixtures replay` |
| M2 intelligence→action | 6 | 0 | `intelligence/triage.py` is deterministic; no provider SDK, no graph, no Slack, no Linear |
| M3 retrieval | 5 | 0 | `MemoryPort` protocol + `InMemoryStore` stub only; no `episodes` table |
| M4 parallel + governor | 5 | 0 | `Budget` contract exists; no ledger, no breaker, no scheduler |
| M5 governed tools + approvals | 6 | 0 | `ToolTier`, `ApprovalRequest` contracts exist; no `mcp/` package |
| M6 replay/eval/traces | 5 | 0 | `Recorder.read_run` exists; no `replay`, `eval`, or OTLP |
| **Total** | **39** | **9.5 (24%)** | |

Against the six v1 definition-of-done bullets (SPEC §1):

| # | v1 DoD | State | Why |
|---|---|---|---|
| 1 | Ingest 4 webhook families + Slack, normalize, dedupe, coalesce storms | ~70% | HTTP sources and dedupe proven; Slack inbound and storm absent |
| 2 | LangGraph supervisor, ≥3 parallel specialists, knowledge, B6 | 0% | triage is rule-based; it never reaches `root_caused` by design |
| 3 | Idempotent Linear create-vs-update + Slack receipt | ~30% | idempotency proven against a Postgres fixture ticket; no external adapter |
| 4 | Privileged tool approval round-trip | 0% | contracts + `AuthPort` protocol only |
| 5 | Flight Recorder records everything, replayable | ~40% | JSONL writer + byte offsets landed; no LLM/tool events exist yet to record; no replay |
| 6 | Budgets, per-agent tool caps, storm brake | 0% | |

**What is genuinely good:** the seams. `contracts/` is a leaf enforced by an AST checker,
`triage(event, *, run_id) -> Conclusion` is already the exact signature a model-backed engine
must satisfy, `TicketingPort` speaks contract models, and the worker is indifferent to how a
Conclusion is produced. The swappability the plan below asks for is mostly already designed;
it is not yet exercised because there is exactly one implementation of everything.

**The decisive blocker is not code.** Nothing in M2 onward can be *proven* (as opposed to
built against fakes) without three owner inputs from SPEC §11.4: a provider key plus the two
model strings, a Slack app with Socket Mode, and a Linear team + API key. Every packet below is
buildable against fakes; the live smoke at the end of M2 is the first thing that waits on Neeraj.

---

## 2. Design rule for every unit below: one seam, one implementation, one fake, one conformance suite

"Smallest of smallest, repurposable, swappable" is made concrete by four rules. A unit that
violates one is not done.

1. **Every capability is a Protocol in `ports/` or a contract in `contracts/`** — never a
   concrete class imported across a package boundary. Consumers type against the Protocol.
2. **Every Protocol ships with a fake in the same PR as its first real adapter,** and a
   **conformance test suite** parametrised over `[fake, real]`. The fake is how the rest of
   the system is tested; the real adapter is how it is proven. A second adapter (Jira, OpenAI,
   Telegram) is *only* a new module plus a new parametrisation row.
3. **Selection is configuration, not code.** `settings.ports.*` and `settings.ticketing.provider`
   already exist; every new seam gets a row there, and `prod` fail-closed rules extend to it.
4. **Declarative over imperative wherever a human might want to repurpose it:** specialists are
   registry YAML + prompt files; tools are manifest rows; recipes are YAML. Adding an agent, a
   tool, or a runbook is a data change with a schema test, not a code change.

Packages that do not exist yet and will (from SPEC §3): `intelligence/graph`, `knowledge/`,
`mcp/`, `governor/`, `actions/{linear,slack}`, `recorder/{broadcast,replay,eval}`, plus data
directories `prompts/`, `registry/`, `recipes/`, `evals/`, `compose/`.

---

## 3. Atomic work units

Each unit is: **one behavioural test → observe failure → minimum implementation → focused test
→ five universal gates → one commit.** Units are numbered `<milestone>.<packet>.<unit>` so they
map back to SPEC §12. Dependencies are listed; anything without a dependency on an unlanded unit
can start today, and independent units may run in parallel worktrees.

Legend: **seam** = new Protocol/contract; **impl** = concrete adapter; **fake** = test double;
**data** = YAML/MD/JSON; **wire** = composition-root change.

### M1 remainder — finish the inbox (no owner inputs needed)

| Unit | Kind | Deliverable | Test that proves it | Depends on |
|---|---|---|---|---|
| 1.2.1 | impl | Quarantine row stores raw B1 bytes (`payload_bytes`, `headers`) — migration 0005 | quarantined body is byte-identical on read-back | — |
| 1.2.2 | impl | Rejected (401) delivery writes one B8 `AuditEvent(kind=rejected)` with source, reason, body sha256 | 401 → exactly one audit line, zero `events` rows | — |
| 1.2.3 | impl | Quarantined delivery writes B8 `AuditEvent(kind=quarantined)` | 202 quarantine → one audit line pointing at the row | 1.2.1 |
| 1.4.1 | seam | `StormPolicy` Protocol: `observe(fingerprint, at) -> StormDecision` (`pass`/`coalesce`/`emit_storm`) | protocol conformance on the fake | — |
| 1.4.2 | impl | `WindowStormPolicy` (Postgres counter): 21st distinct fingerprint in 5 min → `emit_storm`; reset after 5 quiet min | boundary tests at 20 vs 21, and at reset − 1s vs +1s | 1.4.1 |
| 1.4.3 | impl | Receiver emits exactly one `AgentEvent(kind=storm)` carrying member fingerprints; members still admitted individually | 25 fingerprints → 25 rows, 1 storm enqueue, members flagged | 1.4.2 |
| 1.4.4 | impl | Worker handles `kind=storm`: one `needs_human` Conclusion, one ticket titled as a storm | storm event → one ticket, members untouched | 1.4.3 |
| 1.1.1 | seam | `AuditBroadcast` Protocol: `publish(AuditEvent)`, `subscribe() -> AsyncIterator` | in-memory fake round-trips | — |
| 1.1.2 | impl | `recorder/broadcast.py` in-process channel, wired after every successful `Recorder.append` | write → subscriber receives same event, file still written first | 1.1.1 |
| 1.1.3 | impl | `smokejumper logs --follow` (Typer) tails the broadcast; `--run <id>` filters | CLI prints N events for N appends and nothing else | 1.1.2 |
| 1.1.4 | impl | `smokejumper runs latest --format id` prints one run id and a newline, nothing else | stdout is exactly `^[0-9a-f-]{36}\n$` | — |
| 1.7.1 | impl | `smokejumper fixtures replay --source <s>` POSTs `fixtures/webhooks/<s>.json` with that source's configured credential | replay → 202; second replay → `dedupe_count` 2 | — |
| 1.6.1 | data | `compose/prometheus/` scrape + one alert rule against faultbox | `docker compose --profile lab config` valid | — |
| 1.6.2 | data | `compose/alertmanager/` posting to `app:8000/webhooks/alertmanager` | Alertmanager config validates with `amtool` | 1.6.1 |
| 1.6.3 | impl | `compose/faultbox/` tiny HTTP app with `POST /fault/{name}` and `DELETE /fault/{name}`; the route is recorded in SPEC §12 M1.6 | fault on → metric flips within one scrape | — |
| 1.6.4 | data | `compose/loki/` + `promtail/` shipping faultbox logs | `log.search` can find an injected line (proven at M5) | 1.6.3 |
| 1.6.5 | wire | `lab` profile in `docker-compose.yml`; `check_host_ports.py` inventory extended | `--profile lab up` → Alertmanager delivery reaches `/runs/{fp}` | 1.6.1–1.6.4 |

M1 exit evidence: `storm-test.txt`, `alertmanager-to-queue.txt`.

### M2 — one model-backed investigation reaches one real ticket

| Unit | Kind | Deliverable | Test that proves it | Depends on |
|---|---|---|---|---|
| 2.1.1 | seam | `PromptRegistry` Protocol: `resolve(ref) -> PromptText(sha256, body)`; `prompt_ref` grammar `agents/<name>@v<N>` | dangling ref raises at boot | — |
| 2.1.2 | impl+data | `GitPromptRegistry` reading `prompts/**/v<N>.md`; seed `supervisor/plan/v1`, `supervisor/synthesize/v1`, `agents/metrics-analyst/v1`, `prompts/CHANGELOG.md` | sha256 of file == recorded sha | 2.1.1 |
| 2.1.3 | seam+data | `AgentSpec` pydantic schema for `registry/agents/*.yaml` (`name, version, prompt_ref, tools[], budget, dispatch.triggers, enabled`); seed `metrics-analyst.yaml` | invalid budget / unknown prompt_ref rejected | 2.1.1 |
| 2.1.4 | impl | `AgentRegistry` loader: boot resolves every `prompt_ref`, computes `prompt_sha256` | missing prompt file fails boot naming the agent | 2.1.2, 2.1.3 |
| 2.2.1 | seam | Widen `ModelProvider.complete` to return `Completion(text, usage, latency_ms, cost_usd: Decimal, model, request_sha256)` | `RecordedModel` conforms | — |
| 2.2.2 | fake | `RecordedModel` gains `record_to(path)` / `replay_from(path)` so a live call can be captured once and replayed forever | replay yields byte-identical text | 2.2.1 |
| 2.2.3 | impl | `DirectProvider` in `ports/model.py` — the **only** module importing the SDK; role→model mapping from `settings.model`; provider chosen by `settings.model.provider` | `tests/architecture` still passes; unit test uses recorded fixture, zero network | 2.2.1, owner input: provider + key |
| 2.2.4 | impl | Every `complete()`/`embed()` appends a B8 `llm_call` event with `prompt_ref, prompt_sha256, model, request_sha256, response, usage, latency, cost` **before** returning | one call → one audit line with all nine fields | 2.2.1, 2.1.1 |
| 2.2.5 | impl | Redaction pass over every B8 payload from `settings.redaction` patterns | a secret in a prompt never reaches disk | 2.2.4 |
| 2.3.1 | seam | `Specialist` Protocol: `async investigate(Assignment, ToolExecutor, ModelProvider) -> Finding` (stateless) | fake specialist returns canned Finding | — |
| 2.3.2 | impl | `PromptSpecialist`: generic implementation driven entirely by an `AgentSpec` (prompt + tool allowlist + budget) — adding an agent is YAML | metrics-analyst spec + recorded model → one Finding with evidence refs | 2.3.1, 2.1.4, 2.2.2 |
| 2.3.3 | seam | `ConclusionEngine` Protocol: `async conclude(AgentEvent, run_id) -> Conclusion`; `DeterministicTriage` adapts today's `triage()` | worker runs unchanged against either engine | — |
| 2.3.4 | impl | `intelligence/graph/state.py` — `InvestigationState` TypedDict; `nodes/{intake,retrieve,plan,dispatch,aggregate,synthesize}.py`, one function each | each node unit-tested in isolation with a fake state | 2.3.1 |
| 2.3.5 | impl | `SupervisorGraph(ConclusionEngine)` compiled on LangGraph with the Postgres checkpointer; `retrieve` returns an empty `KnowledgeBundle` until M3 | one event → B6 with the specialist's Finding cited | 2.3.4, 2.3.2 |
| 2.3.6 | impl | Restart durability: kill process mid-`dispatch`, restart, run resumes from checkpoint | run concludes with the same `run_id`, one ticket | 2.3.5 |
| 2.3.7 | wire | `settings.intelligence.engine: deterministic|supervisor`; `prod` refuses `deterministic` | check-config fails as documented | 2.3.3, 2.3.5 |
| 2.4.1 | seam | Extend `ChannelAdapter` with `post_actions(channel, thread_ts, ApprovalRequest) -> message_ts` and `on_action(callback)` | `FakeChannel` conforms | — |
| 2.4.2 | impl | `SlackSocketAdapter` (async Bolt Socket Mode): mention listener → `RawInbound`; `send`; button plumbing | contract test with fake Slack client | 2.4.1, owner input: Slack app |
| 2.4.3 | impl | Receiver normalizer for Slack mentions → `AgentEvent(source=slack)` with `channel_id, thread_ts` as entities | golden Slack payload → stable fingerprint | 2.4.2 |
| 2.4.4 | impl | `actions/slack_receipt.py`: threads a receipt under the alerting message when Slack-sourced, else posts to configured channel | receipt text contains ticket id and B6 status | 2.4.1 |
| 2.5.1 | test | `TicketingPort` **conformance suite** parametrised over adapters: create, find-open, update, close, create-after-close is a new ticket | `FixtureTicketing` passes | — |
| 2.5.2 | impl | `LinearAdapter` (direct GraphQL, httpx); inspects `errors` on HTTP 200; fingerprint stored as a Linear label or custom field | recorded-response tests; conformance suite passes | 2.5.1, owner input: Linear key + team |
| 2.5.3 | impl | `actions/service.py` routes through `TicketingPort` instead of writing the fixture row directly; `ticket_actions` stays the durable `(fingerprint, run_id)` idempotency ledger | same 25-way concurrency test, now against the port | 2.5.1 |
| 2.5.4 | wire | `settings.ticketing.provider: fixture|linear` | `prod` refuses `fixture` | 2.5.2 |
| 2.6.1 | test | Golden end-to-end: one fixture alert → one recorded run (`golden-run.jsonl`), one B6, one ticket, one Slack receipt; immediate redelivery deduped before the queue; a **second distinct run** on the same fingerprint updates rather than creates | `ticket-idempotency.txt` shows create then update | all M2 |

### M3 — retrieval is real (one owner input: embedding model + dimension)

| Unit | Kind | Deliverable | Test | Depends on |
|---|---|---|---|---|
| 3.1.1 | data+impl | Migration `0006_episodes` at the confirmed pgvector dimension with `valid_at`, `recorded_at`, `superseded_by` | schema test asserts dimension | owner input |
| 3.1.2 | impl | `ModelProvider.embed` routed through the chosen embedding model, recorded as B8 `embed_call` | vector width == `settings.embedding.dimension` | 2.2.3 |
| 3.2.1 | impl | `PostgresMemory(MemoryPort)`: cosine search, `as_of` bi-temporal filter | seeded 3 episodes → nearest first; `as_of` before insert → empty | 3.1.1 |
| 3.2.2 | impl | `write_episode` supersedes by inserting a new row and stamping `superseded_by` on the old one, never deleting | `as_of` at T still returns the old belief | 3.2.1 |
| 3.3.1 | seam+data | `Recipe` schema (`name, triggers.tags[], steps[], tools[]`); loader over `recipes/*.yaml` | invalid recipe fails boot | — |
| 3.3.2 | impl | Trigger matching: event entity tags → matching recipes, deterministic order | golden event matches exactly one seeded recipe | 3.3.1 |
| 3.4.1 | seam | `KnowledgeFacade` Protocol: `async retrieve(AgentEvent, budget) -> KnowledgeBundle` | fake returns fixed bundle | — |
| 3.4.2 | impl | `knowledge/facade.py` composes episodes + recipes + empty `federated` under token/item budget with source refs and scores | bundle never exceeds budget; every item has a ref | 3.2.1, 3.3.2, 3.4.1 |
| 3.5.1 | wire+test | `retrieve` graph node calls the facade; re-run M2 golden seeded with 2 episodes + 1 recipe → B6 cites the refs; recorder holds the exact bundle | `knowledge-bundle.json` matches recorded B3 | 3.4.2, 2.3.5 |

### M4 — parallel, bounded, governed

| Unit | Kind | Deliverable | Test | Depends on |
|---|---|---|---|---|
| 4.1.1 | data | Prompts + registry for `log-analyst`, `change-auditor`; `db-investigator`, `code-investigator`, `precedent-researcher` with `enabled: false` | registry schema test; disabled agents never dispatched | 2.1.4 |
| 4.2.1 | impl | `dispatch` node fans out one `Assignment` per enabled, triggered specialist with `asyncio.gather`; `aggregate` orders by registry order | **barrier test**: three specialists block on a shared barrier and all release — proves concurrency without wall-clock | 2.3.5, 4.1.1 |
| 4.3.1 | seam | `SpendLedger` Protocol: `charge(run_id, tokens, usd: Decimal)`, `remaining(run_id) -> Budget` | fake ledger conforms | — |
| 4.3.2 | impl | `governor/ledger.py` in Postgres; price table from `settings.model.prices`; **unpriced model in `prod` fails boot** | charge → remaining decreases; unpriced prod → ConfigError | 4.3.1 |
| 4.3.3 | impl | Per-agent `max_tool_calls` and per-run token/iteration/wall caps via LangChain call-limit middleware + ledger check | breach synthesises `inconclusive` B6 with partial findings — never an exception out of the graph | 4.3.2, 4.2.1 |
| 4.4.1 | seam | `CircuitBreaker` Protocol: `record_success()`, `record_failure()`, `state`, `pause_until` | fake conforms | — |
| 4.4.2 | impl | Provider breaker: 3 consecutive failures → 60s pause, open runs get `needs_human` | tests at 2 vs 3 failures; at pause − 1s vs +1s | 4.4.1 |
| 4.4.3 | impl | Worker max in-flight = 3 (semaphore) and stale-pending reclaim (`XAUTOCLAIM` after idle ms) | 4th message waits; a dead consumer's pending entry is reclaimed | — |
| 4.4.4 | impl | Storm brake: `lag > 25` → only `critical|high` dequeued | tests at 25 vs 26 | — |
| 4.5.1 | seam | `Scheduler` Protocol: `every(interval, job)`, `start()`, `stop()` | fake runs jobs on demand | — |
| 4.5.2 | impl | APScheduler adapter with three jobs: registry sync, approval-expiry sweep, recipe-driven scheduled investigations emitting ordinary B2 | each job unit-tested via the fake | 4.5.1 |

### M5 — governed tools and the approval round-trip

| Unit | Kind | Deliverable | Test | Depends on |
|---|---|---|---|---|
| 5.1.1 | seam+data | `mcp/manifest.yaml` schema: `tools[{name, tier, server, description}]`; loader | unknown tool, duplicate name, missing tier, registry tool absent from manifest → boot failure, each its own test | — |
| 5.2.1 | seam | `ToolExecutor` Protocol: `async call(ToolCall, *, agent) -> ToolResult` | fake executor records calls | — |
| 5.2.2 | impl | `mcp/gateway.py` — the single MCP client, in-memory transport to in-process FastMCP servers; `tests/architecture` MCP rule stays green | only `mcp/` imports fastmcp | 5.2.1 |
| 5.2.3–5.2.8 | impl | One FastMCP server module per tool: `metric.query` (Prometheus), `log.search` (Loki), `knowledge.search`, `change.list` (PlatformPort), `linear.read`, `recipe.read`. Each is one file with one test against a recorded upstream response | tool returns `ToolResult` with `source_ref` | 5.2.2 |
| 5.3.1 | impl | FastMCP `on_call_tool` middleware denies by tier, raising `ToolError` | privileged call through middleware alone is refused | 5.1.1, 5.2.2 |
| 5.3.2 | impl | Executor re-checks tier from the same manifest before dispatch | privileged call bypassing middleware is refused by executor alone | 5.1.1, 5.2.1 |
| 5.3.3 | impl | Every tool call appends B8 `tool_call` with args sha256, tier, decision, latency; credentials never in payload | one call → one audit line; redaction test | 2.2.5 |
| 5.4.1 | seam+data | Federated descriptor schema (`endpoint, tool_allowlist, prefix`); `mcp/federated/loader.py` through the same client and manifest | stub descriptor imports two prefixed tools; a third advertised tool is dropped | 5.2.2 |
| 5.5.1 | data | `demo_destructive_noop` privileged tool under test configuration only; prod manifest privileged set is empty | prod boot with any privileged tool fails | 5.1.1 |
| 5.6.1 | seam | `ApprovalBroker` Protocol: `mint(binding) -> token`, `consume(token, binding) -> bool`, `expire_before(ts)`; implements `AuthPort` approval half | fake conforms | — |
| 5.6.2 | impl | Postgres broker: 256-bit token, only hash stored, 30-min expiry, **single atomic UPDATE** consume | double-click race test: two concurrent consumes → exactly one true | 5.6.1 |
| 5.6.3 | impl | `approval_wait` LangGraph interrupt node; Slack buttons via `ChannelAdapter.post_actions`; resume on decision | mint → approve → consume → resume; deny path; expiry auto-deny | 5.6.2, 2.4.1, 2.3.5 |
| 5.6.4 | test | Restart durability across an open approval; replay of the decision | run survives process death with interrupt pending | 5.6.3 |

### M6 — reproducible

| Unit | Kind | Deliverable | Test | Depends on |
|---|---|---|---|---|
| 6.1.1 | impl | `recorder/replay.py`: reads run byte range via `runs` index, feeds recorded `llm_call`/`tool_call` outputs into `RecordedModel` + a `RecordedToolExecutor` | replay of golden run yields identical B6 | 2.2.2, 5.2.1 |
| 6.1.2 | impl | `smokejumper replay <run_id>` deterministic by default; `--live` explicit opt-in | CLI exit 0 and prints B6 status | 6.1.1 |
| 6.2.1 | data | Five `evals/*.json` cases from faultbox ground truth | schema test | 1.6.3 |
| 6.2.2 | impl | `smokejumper eval`: per-agent hit rate vs ground truth, no live model; CI requires ≥4/5 | `eval` exits non-zero at 3/5 | 6.2.1, 6.1.1 |
| 6.3.1 | impl | OTLP spans at `ports/model.py` and the executor; `obs` profile with Phoenix | JSONL complete with Phoenix stopped | 2.2.4, 5.3.3 |
| 6.4.1 | test | Faultbox release case end to end → replay → comparison | acceptance script exits 0 | everything |
| 6.5.1 | docs | Remove "planned" labels in SPEC one command at a time, each with its evidence path | `check_doc_contract.py` passes | per unit |

---

## 4. Swap matrix — what a repurposer changes, and how little

| Want to swap | Change | Touches code? |
|---|---|---|
| LLM vendor | new class in `ports/model.py`, row in `settings.model.provider` | one module |
| Ticket tracker (Jira, GitHub, Asana) | new `actions/<provider>.py` passing the 2.5.1 conformance suite; `settings.ticketing.provider` | one module + one parametrise row |
| Chat surface (Telegram, Teams) | new `ChannelAdapter` impl | one module |
| Alert source | new normalizer in `receiver/normalizers/`, fixture, route registration | one module + one fixture |
| Add / remove a specialist | `registry/agents/<name>.yaml` + `prompts/agents/<name>/v1.md` | **no** |
| Add a runbook | `recipes/<name>.yaml` | **no** |
| Add a tool | FastMCP server module + one manifest row | one module + one YAML row |
| Federate an external MCP server | `mcp/federated/descriptors/<name>.yaml` | **no** |
| Reasoning engine (rules vs graph vs someone else's agent) | new `ConclusionEngine` impl; `settings.intelligence.engine` | one module |
| Memory store (pgvector → other) | new `MemoryPort` impl | one module |
| Budget policy | new `SpendLedger` / `CircuitBreaker` impl | one module |

---

## 5. Order and parallelism

Four independent lanes can run at once from today, each in its own worktree:

- **Lane A (inbox close-out, no inputs):** 1.2.x → 1.4.x → 1.1.x → 1.7.1.
- **Lane B (lab, no inputs):** 1.6.1 → 1.6.5.
- **Lane C (intelligence against fakes, no inputs):** 2.1.x → 2.2.1/2.2.2 → 2.3.x. Only 2.2.3 waits on the provider key.
- **Lane D (actions against fakes, no inputs):** 2.5.1 → 2.5.3 → 2.4.1 → 2.4.4. Only 2.5.2 and 2.4.2 wait on Linear/Slack.

Merge order stays M1 → M2 → … because each milestone's exit evidence consumes the prior one's.
Unit counts: M1 remainder 17, M2 26, M3 9, M4 12, M5 ~17, M6 7 — **88 units**, each a single
commit with one behavioural test.

## 6. What Neeraj alone must decide (blocking, in order of when they bite)

1. **Provider + two model strings + key** — blocks 2.2.3 and every live smoke after it.
2. **Slack app (Socket Mode, four scopes, channel id)** — blocks 2.4.2 and the M2 golden run.
3. **Linear team UUID + API key** — blocks 2.5.2.
4. **Embedding model + dimension** — blocks 3.1.1; this is the one irreversible schema choice.

Nothing else in the 88 units needs a human input.
