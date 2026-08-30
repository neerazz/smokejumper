# Smokejumper — atomic agents pre-planning doc

Date: 2026-08-29 · Baseline: `d0ed9fe` · Status: PRE-PLANNING. Not a plan, not a spec change.
Supersedes the agent-decomposition section of `2026-08-29-v1-completion-plan.md`. SPEC.md stays
normative; this doc proposes what SPEC §5.3 should become before anything in M2+ is planned.

---

## 0. Verdict

> **Read with** [`2026-08-29-reference-architecture-analysis.md`](2026-08-29-reference-architecture-analysis.md): per-component adopt / consume / copy / build verdicts with library facts, and the contract corrections (§4 there) that supersede the enums assumed below.

**The current design's unit of work is wrong-sized.** SPEC §5.3 has three specialists cut by
*data plane* (Metrics Analyst, Log Analyst, Change Auditor). That is how Cleric and Resolve cut
their workers, and it is the coarsest cut that still works — each one is "the person who knows
Datadog," a persona with a blob prompt, unswappable and untestable as a unit.

The right unit, converged on by every mature reference (Anthropic research system, Magentic-One,
MetaGPT, OpenAI handoffs, ADK): **one bounded question → one typed answer**, with its own prompt
file, input/output schema, tool allowlist, budget, and eval set. Not one tool (too fine — every
hop is a lossy model call), not one role (too coarse — the blob).

Three things follow, and they are the whole doc:

1. **The agent catalog is a catalog of questions, not of data sources.** §3 lists 32 of them,
   each with what it witnesses, what it answers, and whether it acts. The three SPEC specialists
   become roughly nine question-agents; the data planes become *tools*, not agents.
2. **General-purpose falls out of separating question from evidence source.** "What changed
   last?" is the same question for a Kubernetes deploy, an Airflow DAG edit, a feature flag, a
   model version, or a payments-provider config. The agent is domain-agnostic; the *witness
   adapter* behind the tool is domain-specific. §4 shows six domain packs on one agent set.
3. **Six pieces are missing from Smokejumper's design that the field is also missing,** and
   two of them are cheap because the Flight Recorder already exists: per-agent cost governance,
   deterministic replay, immutable evidence snapshots, an adversarial verifier, a mitigation
   verifier, and no-fault (healthy-system) evals. §5.

What is *not* changing: contracts as the leaf, LangGraph as the runtime, MCP as the only tool
path, prompts immutable in git, JSONL as the audit truth, the human gate at remediation. Those
are load-bearing and the research confirmed them (every one of 14 surveyed products gates at
remediation, never at diagnosis).

---

## 1. The unit: skill / agent / workflow — three layers the references keep blurring

| Layer | What it is | Has LLM? | Has I/O schema? | Where it lives | Swap cost |
|---|---|---|---|---|---|
| **Skill** | Knowledge: how to read a Prometheus histogram, what a PagerDuty priority means, how to write a blameless timeline | No | No | `skills/<name>/SKILL.md` ≤500 lines, refs one level deep | copy a directory |
| **Agent** | One bounded question, one typed answer, one prompt, one tool allowlist, one budget, one eval set | Yes, exactly one context | Yes, both | `registry/agents/<name>.yaml` + `prompts/agents/<name>/vN.md` + `schemas/agents/<name>.{in,out}.json` + `evals/agents/<name>/*.json` | one directory, no code |
| **Workflow** | Deterministic sequence / fan-out / loop of agents where the order is already known | No (LangGraph edges, ADR-0003) | Yes (state) | `intelligence/workflows/<name>.py` + `registry/workflows/<name>.yaml` | one YAML |

**Only the middle layer is the unit of work.** A skill is not an actor. A workflow is not
intelligent. Putting knowledge into an agent prompt makes it unshareable; putting sequencing into
an agent prompt makes it non-deterministic. Both are the drift this doc exists to prevent.

### 1.1 Sizing rule, with the failure mode on each side

Split into a separate agent when **any** of:
- the answer can be stated as a schema (a list of deploys, a yes/no with confidence, a ranked list);
- the question is read-only and can run in parallel with siblings (LangChain: "read actions are
  inherently more parallelizable than write actions");
- the tool list is long enough that one agent picks the wrong tool (LangGraph's own split criterion).

Merge into one agent when **any** of:
- two steps share state that must stay consistent (Cognition: "actions carry implicit decisions");
- the order is fixed — then it is a *workflow*, not an agent, and no LLM chooses the order.

Failure modes, named so we avoid them:
- **Too fine (one tool per agent):** ~15× chat tokens (Anthropic's measured ceiling), a lossy
  summary at every boundary, and the decision that mattered gets dropped between hops.
- **Too coarse (one persona per data source — where SPEC is today):** prompt mixes routing,
  domain knowledge, and output format; cannot swap model/tool/eval per question; no single
  expected output, so no unit test.

### 1.2 Atomic agent contract (extends B11, does not replace it)

B11 `Assignment{agent, question, context_slice, budget}` → `Finding{agent, hypothesis, evidence,
confidence, budget_spent}` already exists and is right. It needs four additions, each traceable to
a reference:

```yaml
# registry/agents/change-correlator.yaml          — the SPEC §5.3 registry entry, widened
name: change-correlator                            # == directory name (Skills spec, Claude Code)
version: 1                                         # bumps with any behaviour change
description: >                                     # ≤1024 chars; this IS the routing API (ADK)
  Ranks changes that landed on the affected entities in the window before onset.
  Use when an event names at least one entity and an occurred_at.
question: "What changed on {entities} between {t0} and {occurred_at}?"
prompt_ref: agents/change-correlator@v1            # ADR-0020, unchanged
input_schema:  schemas/agents/change-correlator.in.json     # validated BEFORE the run (OpenAI handoff input_type)
output_schema: schemas/agents/change-correlator.out.json    # validated AFTER; must include confidence + evidence refs
tools: [change.list]                               # MCP manifest names; allowlist, nothing inherited
skills: [change-forensics]                         # SKILL.md preloaded, ≤5k tokens
model_role: worker                                 # SPEC §5.10 role indirection, unchanged
budget: {max_tool_calls: 8, max_tokens: 20000, max_turns: 6, timeout_s: 60}   # Anthropic 3–10 ladder
side_effects: read                                 # read | draft | act — `act` never runs in parallel and always crosses B5
phase: investigate                                 # detect|triage|investigate|mitigate|communicate|resolve|learn|prevent
generality: agnostic                               # agnostic | infra — see §4
dispatch: {triggers: [entities_present, occurred_at_present]}
evals: evals/agents/change-correlator/             # ≥20 cases incl. ≥3 no-fault cases (§5.6)
```

The handoff record — the *only* thing that crosses an agent boundary — is B11 `Finding` plus
`artifact_ref` (pointer to the full result in the recorder, ADK `output_key` / Anthropic
"artifact systems") and `open_questions[]`. The parent gets a ≤2k-token Finding and a pointer,
never the trace. Full traces stay in JSONL for replay and postmortem.

### 1.3 Prompt file shape

`prompts/agents/<name>/v<N>.md` stays prompt-only (ADR-0020's reason: one file changes for one
reason). A prompt has five fixed sections so every agent reads the same way and a reviewer can
diff behaviour, not structure:

```
# <name> v<N>
## Question            — the one question, with {placeholders} matching input_schema
## Witnesses           — what evidence you may consult, by tool name, and what each is good for
## Method              — how to answer; cite the skill(s); name the failure mode to avoid
## Answer format       — restates output_schema in prose; requires evidence_ref per claim
## Refusals            — when to return `inconclusive` instead of guessing; never overclaim
```

Supervisor prompts (`prompts/supervisor/{plan,synthesize,verify}/vN.md`) follow the same five
sections. `verify` is new (§5.4).

---

## 2. What each agent *witnesses* — the evidence sources, as ports

An agent never touches a vendor. It calls MCP tools; each tool is backed by a **witness port**
with one adapter per vendor. This is the seam that makes the agent set general-purpose (§4) and
it is the list of things the system can see at all. Eight witness ports cover every question in §3:

| Witness port | Question family it serves | v1 adapter (local) | Later adapters |
|---|---|---|---|
| `ChangeSource` | what changed | git log + `PlatformPort` fixture | ArgoCD, GitHub deployments, LaunchDarkly, Terraform Cloud, Airflow DAG history, model registry |
| `MetricSource` | is anything saturated / did the fix work / how many users | Prometheus | Datadog, CloudWatch, dbt test results, model-quality metrics |
| `LogSource` | dominant new error signature | Loki | Datadog Logs, CloudWatch Logs, Splunk |
| `TraceSource` | where in the request path does it first fail | (none v1) | Tempo, Jaeger, Datadog APM |
| `TopologySource` | blast radius, dependency, ownership | static `topology.yaml` | service catalog (Backstage), K8s owner refs, Airflow DAG graph, payments provider map |
| `IncidentHistorySource` | have we seen this before | `episodes` (M3) + recipes | Linear/Jira closed incidents, postmortem repo |
| `ExternalStatusSource` | is it ours or theirs | (none v1) | statuspage.io feeds, cloud health APIs, payments-processor status |
| `ChatSource` | timeline, hypotheses in flight, handoff | Slack thread (M2) | Teams, incident channel transcript |

Every witness read is recorded as B8 `tool_call` with the query text, timestamp, result hash,
and a **snapshot of the result** (§5.3). That is what makes a Finding's `evidence_ref` resolvable
after the vendor's retention window closes.

---

## 3. The agent catalog — 32 questions in eight phases

Columns: **Q** = the one question · **Witnesses** = witness ports/tools · **Out** = output schema
(all outputs also carry `confidence`, `evidence_refs[]`, `budget_spent`) · **Side** = read / draft /
act · **Gen** = agnostic (same agent, swap adapters) or infra (needs infra-shaped data).

Rank within a phase is build order: value × how badly humans do it × safety of automating.

### Detect (runs before or at admission; mostly deterministic today)

| # | Agent | Q | Witnesses | Out | Side | Gen |
|---|---|---|---|---|---|---|
| D1 | `symptom-classifier` | Is a user actually hurt, or is this an internal cause signal? | event, MetricSource (golden signals), SLO defs (skill) | `{user_impacting: bool, signal: symptom\|cause}` | read | agnostic |
| D2 | `storm-root-picker` | Which member of this storm fired first and is upstream of the rest? | storm event members, TopologySource | `{root_fingerprint, ordering[]}` | read | agnostic |
| D3 | `alert-quality-auditor` | Which alerts fail the five questions (actionable, urgent, novel, user-impacting, one owner)? — weekly | IncidentHistorySource, dedupe counts | `{kill[], tune[], keep[]}` | draft | agnostic |

Deterministic Receiver dedupe and storm detection stay code (SPEC §5.1). D2 is the first thing
that needs a model in the storm path and it runs *after* the `kind=storm` event exists.

### Triage (the current `triage.py` becomes T1+T2 composed deterministically)

| # | Agent | Q | Witnesses | Out | Side | Gen |
|---|---|---|---|---|---|---|
| T1 | `impact-quantifier` | How many users / requests / dollars per minute, which segments, with denominator? | MetricSource, TopologySource (tenant map) | `{affected, denominator, unit, segments[]}` | read | agnostic |
| T2 | `severity-assessor` | What SEV per *our* rubric, and should it be declared? | T1 output, severity rubric (skill), TopologySource | `{sev, declare: bool, rubric_rows_hit[]}` | read | agnostic |
| T3 | `ownership-resolver` | Who owns the affected entities and who is reachable now? | TopologySource, on-call schedule tool | `{owners[], reachable_now[]}` | read | agnostic |
| T4 | `known-issue-matcher` | Have we seen this before, or is it a known upstream outage? | IncidentHistorySource, ExternalStatusSource | `{match: prior_incident\|vendor\|novel, ref}` | read | agnostic |

### Investigate (the fan-out; all read-only, all parallel-safe)

| # | Agent | Q | Witnesses | Out | Side | Gen |
|---|---|---|---|---|---|---|
| I1 | `change-correlator` | What changed on the affected entities in the window before onset? | ChangeSource | `{candidates[{change, delta_s, kind}]}` ranked | read | agnostic |
| I2 | `saturation-finder` | Is any resource at or near a hard limit? | MetricSource | `{saturated[{resource, pct, limit}]}` | read | infra |
| I3 | `error-signature-summarizer` | What is the dominant *new* error signature and where does it first appear? | LogSource, TraceSource | `{signature, first_seen, first_component, sample}` | read | infra |
| I4 | `blast-radius-mapper` | What is downstream and about to break? | TopologySource, MetricSource | `{downstream[{entity, eta_s}]}` | read | agnostic (needs a graph) |
| I5 | `vendor-fault-checker` | Is this ours or theirs? | ExternalStatusSource | `{verdict: ours\|theirs\|unknown, ref}` | read | agnostic |
| I6 | `precedent-researcher` | What did the last similar incident turn out to be, and did that fix work? | IncidentHistorySource | `{precedents[{ref, cause, fix, worked}]}` | read | agnostic |
| I7 | `hypothesis-tracker` | Which theories are open / refuted / confirmed, from the channel so far? | ChatSource | `{hypotheses[{text, state, evidence_refs}]}` | read | agnostic |
| I8 | `bisection-planner` | Which single test discriminates the most open hypotheses at lowest risk? | I7 output, TopologySource | `{next_test, discriminates[], risk}` | draft | agnostic |

I1–I3 are what SPEC's Change Auditor / Metrics Analyst / Log Analyst actually do once the
persona is removed. They are smaller, and they are exactly the "what changed last / what is full /
what is the new error" trio the SRE Book names as the top three troubleshooting heuristics.

### Verify (new — §5.4; runs after Investigate and after any Mitigate)

| # | Agent | Q | Witnesses | Out | Side | Gen |
|---|---|---|---|---|---|---|
| V1 | `adversarial-verifier` | For each candidate cause: what evidence would *disprove* it, and does that evidence exist? | all Findings + witness tools | `{per_candidate[{status: validated\|invalidated\|inconclusive, disproof_attempted}]}` | read | agnostic |
| V2 | `temporal-order-checker` | Does every claimed cause precede its claimed effect in the recorded timestamps? | all Findings' evidence_refs | `{violations[]}` | read | agnostic |
| V3 | `mitigation-verifier` | Did the action actually work, or did recovery coincide? | MetricSource pre/post, action record | `{verified: bool, curve_ref}` | read | agnostic |

### Mitigate (draft is free; act always crosses B5 and never runs in parallel)

| # | Agent | Q | Witnesses | Out | Side | Gen |
|---|---|---|---|---|---|---|
| M1 | `mitigation-ranker` | Fastest *reversible* action that stops the bleeding without knowing root cause? | recipes, cascading-failure playbook (skill), V1 output | `{options[{action, reversible, risk, precondition}]}` | draft | agnostic |
| M2 | `runbook-stepper` | Which runbook applies and which step are we on? | recipes, ChatSource | `{recipe_ref, step, stale: bool}` | draft | agnostic |
| M3 | `rollback-executor` | Is the last change reverted and healthy? | ChangeSource (write), then V3 | `{reverted, health}` | **act** | infra |
| M4 | `flag-toggler` | Is the offending path off? | flag tool (write), then V3 | `{toggled, health}` | **act** | agnostic |

M3/M4 are the privileged tier. They ship `enabled: false` with empty privileged manifest (SPEC
decision 5, ADR-0005) and exist so the B5 round-trip has a real caller at M5.

### Communicate (drafts are read-only; posting is gated)

| # | Agent | Q | Witnesses | Out | Side | Gen |
|---|---|---|---|---|---|---|
| C1 | `timeline-scribe` | What happened, when, by whom? | ChatSource, B8 audit | `{timeline[{ts, actor, what, ref}]}` | read | agnostic |
| C2 | `internal-update-drafter` | What do execs and other teams need to know right now, in three lines? | C1, T1, I7 | `{update_md, next_due_ts}` | draft | agnostic |
| C3 | `status-page-drafter` | What can we tell customers that is true, calm, and non-committal on cause? | T1, approved-language templates (skill) | `{draft_md}` | draft | agnostic |
| C4 | `stakeholder-notifier` | Who must be told by when, by contract or law? | TopologySource (customer map), SLA/regulatory skill | `{notify[{who, by_ts, why}]}` | read | agnostic |
| C5 | `handoff-packager` | What does the next responder need to take over cold? | C1, I7, open actions | `{brief_md, requires_ack}` | draft | agnostic |

### Resolve

| # | Agent | Q | Witnesses | Out | Side | Gen |
|---|---|---|---|---|---|---|
| R1 | `recovery-confirmer` | Fully recovered — queues drained, retries settled, caches fresh — not just error rate? | MetricSource, queue depth tools | `{recovered: bool, residual[]}` | read | agnostic |
| R2 | `divergence-tracker` | What did we hand-edit during the incident that must be reverted or codified? | ChangeSource (incident window), B8 | `{cleanup[]}` | read | agnostic |

### Learn / Prevent (scheduled, never on the alert path)

| # | Agent | Q | Witnesses | Out | Side | Gen |
|---|---|---|---|---|---|---|
| L1 | `postmortem-drafter` | Factual narrative with impact numbers and contributing factors? | C1, T1, I*, V1 | `{draft_md}` | draft | agnostic |
| L2 | `contributing-factor-extractor` | What *set* of conditions had to be true — not one root cause? | L1, IncidentHistorySource | `{factors[{text, evidence_refs}]}` | read | agnostic |
| L3 | `action-item-gate` | Is each item specific, single-owner, prioritized, tied to a factor? | L1 items | `{items[{pass, rewrite}]}` | read | agnostic |
| P1 | `action-item-chaser` | Which committed fixes are overdue, and which incidents repeat because of it? — weekly | TicketingPort read, IncidentHistorySource | `{overdue[], repeats[]}` | draft | agnostic |
| P2 | `trend-analyst` | Which contributing factors recur? — monthly | IncidentHistorySource | `{recurring[{factor, count, denominator}]}` | read | agnostic |
| P3 | `expiry-forecaster` | What hits a hard limit (quota, cert, disk, id-space) in 30/90 days? — daily | MetricSource, cert/quota tools | `{warnings[{what, when}]}` | read | infra |

**Counts:** 32 agents. 25 agnostic, 7 infra. 26 read, 4 draft, 2 act. Danluu's ~200 public
postmortems put config + deploy changes as the two largest cause buckets (~65 of ~200), and
capacity + DNS/cert at ~35 — I1 and P3 alone cover roughly half of recorded causes.

**Build order across phases (first ten):** I1, T1, C1, C2, V1, V3, R1, I2, P1, P3. The research
verdict was blunt: the highest-value automation is not diagnose-and-fix, it is the six jobs humans
reliably skip under stress — impact quantification, change correlation, timeline scribing, update
cadence, action-item follow-through, trend analysis. All six are read-only and run on data that
already exists.

---

## 4. General-purpose by construction — six domain packs on one agent set

A **domain pack** is: a set of witness adapters + a topology file + a severity rubric skill +
a set of recipes + eval fixtures. No agent changes. This is the test of the design: if a pack
needs a new agent, the agent was domain-shaped and should be split.

| Domain pack | "Change" adapter | "Impact" metric | "Recovery" means | Agents that gain weight | Agents that go quiet |
|---|---|---|---|---|---|
| **Infra / ops** (v1 lab) | ArgoCD, K8s rollout, Terraform | error rate, latency | golden signals green + queues drained | I2, I3, M3 | — |
| **Data pipeline** | Airflow/dbt DAG edits, schema migrations, upstream source changes | rows late / stale dashboards / downstream consumers | backfill complete, freshness SLA met | I1, I4 (DAG is the graph), R1 | I3 (traces rare) |
| **Security incident** | IAM changes, secret rotations, dependency bumps | accounts / records exposed | containment confirmed, breach clock stopped | C4 (regulatory clocks become mandatory), C1, R2 | M1 (playbook differs — swap the skill) |
| **Payments / fintech** | processor config, routing rules, ledger code | dollars failed / auths declined / ledger drift | settlement + reconciliation clean, not just API 200 | T1 (the centre), R1, R2 | I2 |
| **ML model** | model version, feature pipeline, training cut | quality/drift metric, business KPI | prior model restored or fallback verified | I1, M3 (= rollback to prior model), V3 | I3 |
| **Support escalation** | product release, policy change | tickets / accounts affected | ticket backlog drained | T3, C2–C5, P1 | I2, I3, I4 |

Two things make this real rather than aspirational:

1. **`generality: agnostic` is enforced, not asserted.** A conformance test runs every agnostic
   agent's eval set against ≥2 domain packs' fixtures. An agent that passes only on infra
   fixtures is re-tagged `infra` or split.
2. **Skills carry the domain vocabulary, agents do not.** `severity-rubric`, `cascading-failure-
   playbook`, `regulatory-clocks`, `reconciliation-checks` are skills per pack. The agent prompt
   says "apply the severity rubric skill"; it never says "P1 means >5% of checkouts."

---

## 5. Missing pieces — in Smokejumper's design *and* in the field

Ranked by how universal the gap is across the 14 surveyed products, with what Smokejumper
already has that makes each cheaper than it looks.

| # | Missing | Field status (of 14) | Smokejumper today | What closes it |
|---|---|---|---|---|
| 5.1 | **Per-agent cost governance** — budget, stop condition, price table, fail-closed on unpriced model | 12/14; only Grafana Assistant (token caps, metering, $2/1M overage) and HolmesGPT (tool output capped at 15% of context, $0.01–0.39 per eval case) publish one; third-party measures 20–50k tokens/incident uncontrolled | `Budget` contract, `ToolResult.cost: Decimal` required, §5.7 ledger *planned* | budget is per **agent file**, not per run; ledger charges per Finding; breach → `inconclusive` with partials (already SPEC's rule) |
| 5.2 | **Deterministic replay** against frozen evidence | 12/14 missing; only Cleric's activity log and HolmesGPT's traces come close | JSONL recorder with byte offsets, `Recorder.read_run`, `RecordedModel` stub — the hard part exists | record every witness read (5.3) so replay feeds recorded tool results, not just recorded completions |
| 5.3 | **Evidence provenance as an artifact** — snapshot, not deep-link | 13/14 deep-link only; RCA becomes unverifiable when retention expires; OpenRCA 2.0: 14.5 pts of "right service, ungrounded chain" | `Finding.evidence: list[str]` — strings | new contract `EvidenceRecord{ref, tool, query, ts, result_sha256, snapshot_ref}`; `evidence_refs` must resolve to one; recorder stores the snapshot |
| 5.4 | **Adversarial verification as a separate agent** | 5/14 have a distinct verifier (Resolve, incident.io, Cleric post-fix, Flow-of-Action Judge) | none; synthesize trusts findings | V1 + V2 run *after* aggregate, *before* synthesize; synthesize may not mark `root_caused` unless V1 says `validated` and V2 has no violations |
| 5.5 | **Confirm diagnosis via mitigation** | 11/14 missing (Cleric fix-verifier; Komodor Validation Engine and Grafana "was this the cause?" are partial); ORCA-Bench names it the open problem | none | V3 after every `act`; a Conclusion may reach `mitigated` only via V3 `verified: true` |
| 5.6 | **No-fault / healthy-system control** | 12/14; AIOpsLab: one agent passed the no-fault case; Causely: 67% false-positive baseline | none; evals planned at M6 only for fault cases | every agent eval set carries ≥3 no-fault cases; expected output `inconclusive` with empty candidates; a prompt that hallucinates on healthy data fails CI |
| 5.7 | **Published accuracy with denominator and judge** | 10/14 give customer percentages with no denominator; the four that publish: Cleric (pairwise Elo), RCACopilot (0.766 micro-F1 / 653), OpsAgent (84% / 10,492), HolmesGPT (63 cases × 3 iters, opus-5 94%, sonnet-5 83%) | none | `smokejumper eval` reports `hit / total` per agent and the judge rubric; pairwise judge (Cleric's method: 67% agreement vs 27% absolute) |
| 5.8 | **Portable skill library across tenants** | 14/14 tenant-isolated by policy | skills don't exist yet | skills are files in git with no tenant data; domain packs (§4) are the portability unit |

**One pattern the field has converged on that Smokejumper lacks entirely: hypothesis as first-class
typed state.** Grafana Assistant (open / root cause / symptom / disproven / blocked), Datadog
(validated / invalidated / inconclusive), Cleric (confirmed / ruled out) all carry it. Here it is
one contract, `Hypothesis{text, state, evidence_refs[], owner_agent}`, written by the plan node,
updated by I7 and V1, read by synthesize and C2. It is the shared whiteboard (ADK `session.state`,
Magentic-One task ledger) and the reason `root_caused` can be gated mechanically (5.4).

What is **not** missing and should not be re-litigated: the human gate at remediation (14/14
agree), read-only witness access (13/14), and citations in every output (all mature products).
The field's bottleneck per the benchmarks is reasoning and grounding, not data access — which is
why 5.3–5.6 rank above adding more integrations.

---

## 6. Workflows — where the LLM does *not* decide

Diagram of the proposed architecture: [`architecture/system/proposed-atomic-agents.svg`](../../architecture/system/proposed-atomic-agents.svg)
(source [`proposed-atomic-agents.mmd`](../../architecture/system/proposed-atomic-agents.mmd); re-render with
`python3 scripts/render_architecture.py architecture/system/proposed-atomic-agents.mmd`). C4 Level-3 component view (every component by package, landed / planned / proposed, plus the step
ledger of one run): [`architecture/system/c3-components.svg`](../../architecture/system/c3-components.svg),
hand-laid by [`_gen/c3_components.py`](../../architecture/_gen/c3_components.py). The canonical
`system/c2-containers.svg` is unchanged on purpose — it must agree with SPEC, and SPEC has not
been amended yet (§9).

Order is known for the alert path, so it is a deterministic graph (ADR-0003), not a planning LLM.
The supervisor's `plan` node chooses *which* investigate agents to dispatch and their
`context_slice`; it never chooses phase order.

```
admit(B2) ──► triage ──────────────► investigate ─────► verify ─────► synthesize(B6) ──► actions
              T1 ∥ T3 ∥ T4          I1 ∥ I2 ∥ I3 ∥ I4   V1 → V2                          ticket
              then T2               ∥ I5 ∥ I6            (gate root_caused)              receipt
                                    (plan picks subset,
                                     budget bounds it)
                              ┌─────────────────────────────────────────────┐
                              │ optional, on Slack thread activity: I7, I8, │
                              │ C1 continuous, C2 on timer, C5 on handoff   │
                              └─────────────────────────────────────────────┘
mitigate (only via B5): M1 draft → human → M3/M4 act → V3 → R1 → R2 → close
learn (scheduled, off the alert path): L1 → L2 → L3 ; P1 weekly ; P2 monthly ; P3 daily
```

Effort ladder, enforced in `registry/workflows/alert.yaml` not prose (Anthropic's operating
points, to be re-tuned on our evals): `severity in {low}` → T1+T2 only, ≤2 agents; `medium` →
+I1, I2, ≤4 agents; `high|critical` → full investigate set + V1/V2, ≤8 agents, ≤8 tool calls each.

Four workflows total: `alert` (above), `slack-question` (I7 → plan → subset → synthesize),
`mitigate` (B5-gated), `learn` (scheduled). Each is one YAML naming agents and edges.

---

## 7. Use cases this has to witness end to end (acceptance shapes, not tests yet)

1. **Deploy regression, infra pack.** Faultbox fault → Alertmanager → T1 counts affected
   requests with denominator → I1 finds the deploy 4 min before onset → I3 finds the new
   signature → V1 tries to disprove (was the signature present before the deploy? no) → V2 confirms
   order → B6 `root_caused` citing three `EvidenceRecord`s → one Linear ticket → Slack receipt →
   `replay` reproduces the same B6 from snapshots with the vendor down.
2. **Healthy-system alert (false positive).** Same pipeline, no fault injected, a flapping
   monitor → every investigate agent returns empty candidates → V1 has nothing to validate → B6
   `inconclusive` with the explicit finding "no change, no saturation, no new signature in window"
   → ticket updated, not opened → this run is the no-fault eval case.
3. **Storm.** 25 alerts in 5 min → deterministic storm event → D2 picks the upstream root →
   one investigation on the root, members linked → one ticket titled as a storm.
4. **Data pipeline pack, same agents.** dbt freshness SLA alert → T1 counts stale downstream
   models (denominator: models depending on the source) → I1 finds a schema migration on the
   upstream table → I4 walks the DAG for blast radius → R1 confirms backfill complete before
   close. Zero agent changes; new `ChangeSource` and `TopologySource` adapters.
5. **Slack question mid-incident.** "@smokejumper what have we ruled out?" → I7 reads the
   thread → returns the hypothesis board with states and refs → C2 drafts the next update.
6. **Privileged action.** M1 ranks rollback first → B5 approval in Slack → M3 executes via the
   demo noop under test config → V3 verifies → `mitigated` only if verified.
7. **A week later.** P1 finds the postmortem's action item overdue and the same fingerprint
   re-opened twice → drafts the nudge with both refs.

---

## 8. References the design leans on (read in this session, not recalled)

Decomposition and sizing: Anthropic *Building effective agents* and *multi-agent research
system* (one consideration per call; brief = objective + output format + tools + boundaries; 3–10
call ladder; ~15× tokens); Magentic-One (task/progress ledgers, stall → replan); MetaGPT
(structured documents, not dialogue, to stop cascading hallucination); OpenAI Agents SDK (typed
handoff `input_type`); LangGraph multi-agent docs (split when the tool list causes routing
errors; read parallelises, write does not); Google ADK (deterministic Sequential/Parallel/Loop
agents where order is known); Agent Skills spec (skill ≠ agent; ≤500 lines; progressive
disclosure). Counter-view weighed: Cognition *Don't build multi-agents* (share full traces for
write paths) — adopted for `act` agents, rejected for read fan-out.

Product patterns: Traversal (causal constraints, "errs toward silence", ORCA-Bench 25%/10% and
7–40% hallucination), Cleric (per-source subagents, separate fix-verifier, pairwise-Elo eval at
$0.06/comparison), Resolve (adversarial Verifier), incident.io (challenger agent), Datadog Bits
(validated/invalidated/inconclusive per hypothesis), Grafana Sift (deterministic named analyses),
HolmesGPT (eval with injected unique values + recorded tool calls), RCACopilot (handler per alert
type; 0.766 micro-F1 on 653), AIOpsLab (no-fault case; RCA ≤45%), OpenRCA 2.0 (ungrounded-chain
gap), failure taxonomy (evidence insufficiency, spurious causation, fabricated evidence, temporal
misordering — V1/V2/5.3 are the direct answers).

SRE practice: Google SRE Book (troubleshooting heuristics; monitoring's five questions;
cascading-failure playbook; postmortem culture), SRE Workbook (incident response; impact data
missing from bad postmortems), PagerDuty response guide (scribe dropped first; 30-min exec
cadence; handoff with ack), Howie guide (contributing factors, not root cause), danluu
post-mortems (config/deploy ~65 of ~200; capacity/DNS/cert ~35), Learning-from-Incidents
(nobody aggregates factors).

Full URL lists are in the three research reports from this session; the numbers above are theirs.

---

## 9. What this changes in SPEC if adopted (not done; listed so the planning step is honest)

1. §5.3 "v1 specialists (3)" → "agent catalog (§3 here), v1 subset = I1, I2, I3, T1, T2, V1, V2,
   C1" — eight question-agents replace three personas; the M2 single-specialist packet becomes
   I1 (change-correlator), because it is the highest-yield question in the public record.
2. §4 gains `EvidenceRecord` (5.3) and `Hypothesis` (5, typed state); B11 `Finding` gains `artifact_ref`, `open_questions`.
3. §5.3 registry schema widens per §1.2 (`question`, `input_schema`, `output_schema`,
   `side_effects`, `phase`, `generality`, `skills`, `evals`).
4. §3 layout gains `skills/`, `schemas/agents/`, `registry/workflows/`, `evals/agents/`.
5. §5.7 budget becomes per-agent-file first, per-run second.
6. §8 acceptance gains the no-fault case (§7.2) and the second domain pack (§7.4).
7. New ADR: *Agents are questions, not roles* — supersedes the persona framing in ADR-0015's
   "specialists are declarative YAML" without changing the LangGraph decision.

---

## 10. Decisions only Neeraj can make before this becomes a plan

1. **Adopt question-sized agents (§1) or stay with three data-plane specialists.** Everything
   else here depends on it.
2. **Which second domain pack proves generality first** — data pipeline (cheapest, DAG is a
   free topology) or payments (closest to Parafin's reality; T1 becomes dollars).
3. **Whether `root_caused` is gated on V1/V2** (5.4). Strict is the recommendation; it is also
   what makes the status honest against the OpenRCA gap.
4. **Whether `EvidenceRecord` snapshots are stored in the JSONL or beside it** — size vs one
   file. Recommendation: beside it, content-addressed, referenced by sha256.
5. The three M2 owner inputs still stand (provider + models, Slack app, Linear team) and are
   unchanged by this doc.
