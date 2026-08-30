#!/usr/bin/env python3
# ruff: noqa
"""Hand-laid C4 Level-3 component diagram for Smokejumper.

Explicit coordinates, no auto-layout. Regenerate the sibling SVG with:
    python3 architecture/_gen/c3_components.py
Then rasterize for review with headless Chrome (see docs/plans/2026-08-29-atomic-agents-preplan.md §6).
"""

from html import escape

W, H = 2200, 2440
out = []
P = out.append

# palette lifted from architecture/system/c2-components.svg
C = {
    "core": ("#e3f3f6", "#0b7285", "#0b3a42"),
    "files": ("#e6f4ea", "#2b8a3e", "#1b4d24"),
    "port": ("#f1f3f5", "#5b6b7a", "#3d4852"),
    "gate": ("#fbf0da", "#9a6700", "#5c3d00"),
    "audit": ("#efeafb", "#6741b8", "#2f1e5c"),
    "store": ("#eef2fb", "#3f5b9a", "#1f2d4a"),
    "ext": ("#ffffff", "#5b6b7a", "#3d4852"),
}
GREY = "#5b6b7a"
INK = "#10334a"


def text(x, y, s, size=12, weight=None, fill=INK, anchor="start", family=None):
    attrs = f'x="{x}" y="{y}" font-size="{size}" fill="{fill}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if anchor != "start":
        attrs += f' text-anchor="{anchor}"'
    if family:
        attrs += f' font-family="{family}"'
    P(f"  <text {attrs}>{escape(s)}</text>")


def status_dot(x, y, st):
    # landed = solid green, planned = hollow navy, proposed = dashed amber
    if st == "landed":
        P(f'  <circle cx="{x}" cy="{y}" r="5" fill="#2b8a3e"/>')
    elif st == "planned":
        P(f'  <circle cx="{x}" cy="{y}" r="5" fill="#ffffff" stroke="#3f5b9a" stroke-width="1.6"/>')
    elif st == "proposed":
        P(
            f'  <circle cx="{x}" cy="{y}" r="5" fill="#ffffff" stroke="#9a6700" stroke-width="1.6" stroke-dasharray="2 2"/>'
        )


TAGC = {
    "ADOPT": "#2b8a3e",
    "CONSUME": "#3f5b9a",
    "COPY": "#0b7285",
    "BUILD": "#9a6700",
    "KEEP": "#5b6b7a",
}


def comp(x, y, w, h, title, lines, kind="core", st="planned", mono=None, ts=12.5, ls=11, tag=None):
    fill, stroke, ink = C[kind]
    dash = ' stroke-dasharray="5 4"' if kind in ("port", "ext") else ""
    P(
        f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{stroke}"{dash}/>'
    )
    status_dot(x + 12, y + 15, st)
    text(x + 24, y + 19, title, ts, "700", ink)
    if tag:
        verb, ref = tag
        label = f"{verb} · {ref}" if ref else verb
        tw = 5.6 * len(label) + 12
        fits_bottom = 36 + 15 * len(lines) + 2 <= h - 18
        fits_title = 24 + 0.62 * ts * len(title) + tw + 14 <= w
        ty = y + h - 18 if fits_bottom else (y + 6 if fits_title else y + h - 6)
        P(
            f'  <rect x="{x + w - tw - 6}" y="{ty}" width="{tw}" height="13" rx="6" fill="#ffffff" stroke="{TAGC[verb]}" stroke-width="0.9"/>'
        )
        text(x + w - 6 - tw / 2, ty + 9.5, label, 8.8, "700", TAGC[verb], "middle")
    yy = y + 36
    for ln in lines:
        text(x + 12, yy, ln, ls, None, ink, family=mono)
        yy += 15
    if mono:
        pass


def pkg(x, y, w, h, name, sub, kind="core"):
    fill, stroke, ink = C[kind]
    P(
        f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#fffdf9" stroke="{stroke}" stroke-width="1.4"/>'
    )
    text(x + 16, y + 26, name, 15, "700", stroke)
    text(x + 16, y + 44, sub, 11, None, GREY)


def arrow(x1, y1, x2, y2, label=None, bold=False, dashed=False, lx=None, ly=None):
    sw = 2.4 if bold else 1.3
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    P(
        f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#3d4852" stroke-width="{sw}"{dash} marker-end="url(#arrow)"/>'
    )
    if label:
        text(lx or (x1 + x2) / 2, ly or ((y1 + y2) / 2 - 6), label, 10.5, None, GREY, "middle")


P(
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
    f'font-family="-apple-system, \'Segoe UI\', Helvetica, Arial, sans-serif" role="img" aria-labelledby="c3-title c3-desc">'
)
P(
    '  <title id="c3-title">Smokejumper C4 Level 3 — components of the app container and the step ledger of one run</title>'
)
P(
    '  <desc id="c3-desc">Every component inside the single app process, grouped by package, with landed / planned / proposed status; the two backing containers; and the ordered ledger of the smallest reported steps in one investigation run.</desc>'
)
P(
    '  <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#3d4852"/></marker></defs>'
)
P(f'  <rect width="{W}" height="{H}" fill="#ffffff"/>')

# ── Title & legend ─────────────────────────────────────────────────────────
text(60, 70, "Smokejumper — C4 Level 3: components inside the app container", 28, "700", INK)
text(
    60,
    98,
    "One process (docker compose service `app`) · every component by package · status against commit d0ed9fe on 2026-08-29 · "
    "reuse verdict per component from docs/plans/2026-08-29-reference-architecture-analysis.md",
    13,
    None,
    GREY,
)
# legend
lx = 60
for st, lab in (
    ("landed", "landed — code + tests exist"),
    ("planned", "planned — in SPEC §12, not built"),
    ("proposed", "proposed — pre-plan only"),
):
    status_dot(lx + 6, 124, st)
    text(lx + 18, 128, lab, 11.5, None, GREY)
    lx += 250
for kind, lab in (
    ("core", "code you build"),
    ("files", "declarative files, zero code"),
    ("port", "port / external"),
    ("gate", "approval-gated"),
    ("audit", "audit spine"),
    ("store", "data container"),
):
    fill, stroke, _ = C[kind]
    dash = ' stroke-dasharray="4 3"' if kind == "port" else ""
    P(
        f'  <rect x="{lx}" y="116" width="22" height="14" rx="3" fill="{fill}" stroke="{stroke}"{dash}/>'
    )
    text(lx + 28, 128, lab, 11.5, None, GREY)
    lx += 200

lx = 60
text(lx, 145, "reuse tag on each box:", 11.5, "700", GREY)
lx += 135
for verb, lab in (
    ("ADOPT", "pip dependency"),
    ("CONSUME", "existing server / hosted"),
    ("COPY", "design copied, we write it"),
    ("BUILD", "nothing exists — ours"),
    ("KEEP", "landed, no change"),
):
    P(
        f'  <rect x="{lx}" y="135" width="{5.6 * len(verb) + 12}" height="13" rx="6" fill="#ffffff" stroke="{TAGC[verb]}" stroke-width="0.9"/>'
    )
    text(lx + (5.6 * len(verb) + 12) / 2, 145, verb, 8.8, "700", TAGC[verb], "middle")
    text(lx + 5.6 * len(verb) + 18, 145, lab, 11, None, GREY)
    lx += 5.6 * len(verb) + 18 + 6.2 * len(lab) + 24
# ── Row A · external systems ───────────────────────────────────────────────
P(f'  <rect x="60" y="158" width="2080" height="84" rx="10" fill="#f8f9fa" stroke="#8a99a8"/>')
text(78, 176, "EXTERNAL SYSTEMS (outside the container)", 12, "700", GREY)
ext = [
    ("Alertmanager", "webhook · peer-network allowlist"),
    ("Grafana", "webhook · shared token · batches"),
    ("Datadog", "webhook · bearer token"),
    ("PagerDuty v3", "webhook · HMAC raw body"),
    ("Generic JSON", "webhook · HMAC sha256="),
    ("Slack · Discord · Telegram", "slack-bolt · discord.py · python-telegram-bot"),
    ("Linear", "GraphQL · tickets out"),
    ("Prometheus · Loki", "lab profile · read tier"),
    ("LLM provider", "SDK · via ports/model.py only"),
]
x = 78
for i, (t, s) in enumerate(ext):
    w = 214
    P(
        f'  <rect x="{x}" y="186" width="{w}" height="46" rx="6" fill="#ffffff" stroke="#5b6b7a" stroke-dasharray="5 4"/>'
    )
    text(x + w / 2, 205, t, 12, "700", "#3d4852", "middle")
    text(x + w / 2, 222, s, 10.5, None, GREY, "middle")
    x += w + 15

# ── Row B · edge packages ──────────────────────────────────────────────────
Y = 270
pkg(60, Y, 720, 330, "receiver/", "deterministic · no LLM · verify before parse · 5 sources landed")
comp(
    76,
    Y + 56,
    220,
    118,
    "routes.py",
    [
        "POST /webhooks/datadog",
        "POST /webhooks/pagerduty",
        "POST /webhooks/grafana",
        "POST /webhooks/alertmanager",
        "POST /webhooks/generic",
    ],
    st="landed",
    tag=("KEEP", "Alerta webhook shape"),
)
comp(
    308,
    Y + 56,
    220,
    118,
    "verification.py",
    [
        "verify_shared_token",
        "verify_hmac_signature",
        "verify_pagerduty_signature",
        "verify_source_ip (CIDR)",
        "constant-time compare",
    ],
    st="landed",
    tag=("KEEP", "vendor schemes"),
)
comp(
    540,
    Y + 56,
    224,
    118,
    "normalizers/",
    [
        "datadog.py · sources.py",
        "pagerduty · grafana · alertmanager",
        "generic · identity-tag allowlist",
        "batch fan-out → N events",
        "recovery → window_closed_at",
    ],
    st="landed",
    tag=("COPY", "Alertmanager v4 + Keep enums"),
)
comp(
    76,
    Y + 186,
    220,
    128,
    "repository.py",
    [
        "admit() — advisory lock per fp",
        "15-min dedupe window",
        "quarantine() — 202 + reason",
        "close_window() on Recovered",
        "outbox: mark_queued / pending",
    ],
    st="landed",
    tag=("COPY", "Keep full/partial dedup"),
)
comp(
    308,
    Y + 186,
    220,
    128,
    "delivery.py (outbox)",
    [
        "dispatch_event → XADD",
        "dispatch_pending retry loop",
        "OutboxHandle.status → /healthz",
        "Redis down ≠ lost event",
    ],
    st="landed",
    tag=("KEEP", ""),
)
comp(
    540,
    Y + 186,
    224,
    60,
    "storm_policy.py",
    ["21st fp in 5 min → kind=storm", "5-min quiet reset"],
    st="planned",
    tag=("COPY", "Robusta GroupingParams"),
)
comp(
    540,
    Y + 254,
    224,
    60,
    "audit for 401 / quarantine",
    ["exact-B1 bytes → B8", "rejected · quarantined kinds"],
    kind="audit",
    st="planned",
    tag=("BUILD", ""),
)

pkg(800, Y, 380, 330, "queue/ · worker.py", "Redis Streams · at-least-once · ack after commit")
comp(
    816,
    Y + 56,
    348,
    74,
    "queue/producer.py",
    ["XADD agentevents maxlen=…", "event UUID reused as run_id"],
    st="landed",
    tag=("KEEP", "redis-py"),
)
comp(
    816,
    Y + 140,
    348,
    100,
    "worker.py — consumer group `intelligence`",
    [
        "XREADGROUP block 2s · count 10",
        "handle(): open_run → engine → apply → close_run",
        "poison payload → ack · failure → leave pending",
        "queue_depth {lag, pending} → /healthz",
    ],
    st="landed",
    tag=("KEEP", ""),
)
comp(
    816,
    Y + 250,
    168,
    64,
    "reclaim (XAUTOCLAIM)",
    ["stale pending of dead", "consumer — M4"],
    st="planned",
    tag=("KEEP", "redis-py"),
)
comp(
    996,
    Y + 250,
    168,
    64,
    "max in-flight = 3",
    ["semaphore · M4", "storm brake lag>25"],
    st="planned",
    tag=("COPY", "Alerta flapping window"),
)

pkg(1200, Y, 400, 330, "app.py · cli.py", "FastAPI + Typer · composition root reads config only")
comp(
    1216,
    Y + 56,
    368,
    84,
    "app.py",
    [
        "GET /healthz — postgres · schema · redis · worker · outbox",
        "GET /runs/{fingerprint} — conclusion + ticket + audit range",
        "lifespan: outbox_task ∥ worker_task",
    ],
    st="landed",
    tag=("KEEP", "FastAPI"),
)
comp(
    1216,
    Y + 150,
    176,
    74,
    "cli: check-config",
    ["validates layered settings", "exits non-zero fail-closed"],
    st="landed",
    tag=("KEEP", "Typer"),
)
comp(
    1408,
    Y + 150,
    176,
    74,
    "cli: fixtures replay",
    ["POST fixture w/ source cred", "--source <s> · M1"],
    st="planned",
    tag=("BUILD", ""),
)
comp(
    1216,
    Y + 234,
    176,
    80,
    "cli: logs · runs latest",
    ["logs --follow (broadcast)", "runs latest --format id", "M1"],
    st="planned",
    tag=("BUILD", ""),
)
comp(
    1408,
    Y + 234,
    176,
    80,
    "cli: replay · eval",
    ["replay <run_id> from JSONL", "eval → hit/total per agent", "M6"],
    st="planned",
    tag=("BUILD", ""),
)

pkg(
    1620,
    Y,
    520,
    330,
    "config.py · ports/",
    "one Settings object · 8 Protocols · prod refuses stubs",
)
comp(
    1636,
    Y + 56,
    488,
    84,
    "config.py — Settings",
    [
        "defaults < base.yaml < <env>.yaml < env vars < flags",
        "_fail_closed: prod ∧ stubbed security port → ConfigError",
        "unpriced prod model → ConfigError (M4) · lab only in local",
    ],
    st="landed",
    tag=("KEEP", "pydantic-settings"),
)
ports = [
    ("AuthPort", "AllowAll"),
    ("GovernancePort", "NoopGovernance"),
    ("TenancyPort", "SingleTenant — real"),
    ("ModelProvider", "RecordedModel"),
    ("PlatformPort", "FixturePlatform"),
    ("TicketingPort", "FixtureTicketing"),
    ("MemoryPort", "InMemoryStore"),
    ("ChannelAdapter", "FakeChannel"),
]
px, py = 1636, Y + 150
for i, (pn, stub) in enumerate(ports):
    cx = px + (i % 4) * 122
    cy = py + (i // 4) * 84
    comp(
        cx,
        cy,
        116,
        74,
        pn,
        [f"stub: {stub}", "real: M2–M5"],
        kind="port",
        st="landed",
        ts=10.5,
        ls=9.5,
    )

# ── Row C · intelligence / knowledge / governor ───────────────────────────
Y = 630
pkg(
    60,
    Y,
    1400,
    640,
    "intelligence/",
    "B2 in → B6 out · never imports actions · the only package that thinks",
)
# left column: current + workflows + supervisor
comp(
    76,
    Y + 56,
    300,
    88,
    "triage.py (current engine)",
    [
        "deterministic · alert-grounded",
        "needs_human | inconclusive only",
        "adapter: DeterministicTriage(ConclusionEngine)",
    ],
    st="landed",
    tag=("KEEP", ""),
)
comp(
    76,
    Y + 154,
    300,
    118,
    "workflows/ — deterministic edges",
    [
        "registry/workflows/alert.yaml",
        "slack-question · mitigate · learn",
        "effort ladder: low ≤2 · med ≤4 · high ≤8 agents",
        "phase order fixed; no LLM chooses it",
        "LangGraph graph + Postgres checkpointer",
    ],
    kind="files",
    st="proposed",
    tag=("ADOPT", "LangGraph 1.2 · @task"),
)
comp(
    76,
    Y + 282,
    300,
    150,
    "supervisor nodes (graph/nodes/*.py)",
    [
        "intake — B2 → state",
        "retrieve — B3 KnowledgeBundle under budget",
        "plan — WHICH agents + context_slice  [llm]",
        "dispatch — N Assignments ∥ (gather)",
        "aggregate — registry-stable order",
        "verify — V1/V2 gate  [proposed]",
        "synthesize — B6  [llm] · root_caused iff verified",
    ],
    st="planned",
    tag=("ADOPT", "LangGraph + pg checkpointer"),
)
comp(
    76,
    Y + 442,
    300,
    100,
    "hypothesis_board.py",
    [
        "Hypothesis{text, state, evidence_refs, owner}",
        "open · validated · invalidated · inconclusive",
        "written by plan/I7/V1 · read by synthesize/C2",
        "checkpointed with graph state",
    ],
    kind="audit",
    st="proposed",
    tag=("BUILD", "no library exists"),
)
comp(
    76,
    Y + 552,
    300,
    62,
    "prompts/supervisor/",
    ["plan/v1.md · synthesize/v1.md · verify/v1.md", "sha256 stamped on every llm_call"],
    kind="files",
    st="planned",
    tag=("KEEP", "git + sha256, ADR-0020"),
)

# middle column: agent runner
comp(
    392,
    Y + 56,
    340,
    250,
    "agent_runner.py — one Assignment → one Finding",
    [
        "1 load registry/agents/<name>.yaml (AgentSpec)",
        "2 resolve prompt_ref → text + sha256",
        "3 preload skills/<s>/SKILL.md ≤5k tokens",
        "4 validate input against schemas/…in.json",
        "5 loop ≤max_turns: model turn → tool call(s)",
        "    each tool call → mcp.gateway (B4)",
        "    each model turn → ports.model (B8 llm_call)",
        "    governor.charge() after every step",
        "6 validate output against schemas/…out.json",
        "7 emit Finding + artifact_ref + open_questions",
        "budget breach → partial Finding, never raise",
        "stateless: no memory between runs",
    ],
    st="planned",
    tag=("COPY", "HolmesGPT safeguards"),
)
comp(
    392,
    Y + 316,
    164,
    100,
    "registry_loader.py",
    [
        "AgentSpec pydantic schema",
        "boot resolves every prompt_ref",
        "hot-reload on Governor tick",
        "disabled agents never dispatch",
    ],
    st="planned",
    tag=("COPY", "PydanticAI AgentSpec shape"),
)
comp(
    568,
    Y + 316,
    164,
    100,
    "prompt_registry.py",
    [
        "GitPromptRegistry",
        "prompts/agents/<n>/vN.md",
        "immutable versions",
        "dangling ref fails boot",
    ],
    st="planned",
    tag=("KEEP", "git, ADR-0020"),
)
comp(
    392,
    Y + 426,
    164,
    90,
    "skill_loader.py",
    ["skills/<name>/SKILL.md", "frontmatter name/desc", "≤500 lines · refs 1 deep"],
    kind="files",
    st="proposed",
    tag=("ADOPT", "agentskills.io spec"),
)
comp(
    568,
    Y + 426,
    164,
    90,
    "schema_validator.py",
    ["schemas/agents/*.in|out", "reject before/after run", "evidence_ref per claim"],
    st="proposed",
    tag=("ADOPT", "langchain ToolStrategy"),
)
comp(
    392,
    Y + 526,
    340,
    88,
    "eval_runner.py → `smokejumper eval`",
    [
        "evals/agents/<name>/*.json · ≥20 cases · ≥3 no-fault",
        "judge: schema_valid · factual · citation · tool_efficiency",
        "reports hit / total per agent · CI ≥ 4/5",
    ],
    st="planned",
    tag=("COPY", "HolmesGPT tests/llm + Inspect AI"),
)

# right column: agent catalog by phase (declarative)
cx0, cy0 = 748, Y + 56
text(
    cx0,
    cy0 - 6,
    "registry/agents/*.yaml + prompts/agents/*/vN.md — 32 question-agents, one directory each, zero code",
    11.5,
    "700",
    "#2b8a3e",
)
cat = [
    (
        "TRIAGE",
        ["impact-quantifier", "severity-assessor", "ownership-resolver", "known-issue-matcher"],
        "files",
        "proposed",
    ),
    (
        "INVESTIGATE ∥ read",
        [
            "change-correlator",
            "saturation-finder",
            "error-signature-summarizer",
            "blast-radius-mapper",
            "vendor-fault-checker",
            "precedent-researcher",
            "hypothesis-tracker",
            "bisection-planner",
        ],
        "files",
        "proposed",
    ),
    (
        "VERIFY (gate)",
        ["adversarial-verifier", "temporal-order-checker", "mitigation-verifier"],
        "files",
        "proposed",
    ),
    (
        "DETECT",
        ["symptom-classifier", "storm-root-picker", "alert-quality-auditor"],
        "files",
        "proposed",
    ),
    (
        "COMMUNICATE",
        [
            "timeline-scribe",
            "internal-update-drafter",
            "status-page-drafter",
            "stakeholder-notifier",
            "handoff-packager",
        ],
        "files",
        "proposed",
    ),
    (
        "MITIGATE",
        [
            "mitigation-ranker (draft)",
            "runbook-stepper (draft)",
            "rollback-executor  ACT",
            "flag-toggler  ACT",
        ],
        "gate",
        "proposed",
    ),
    ("RESOLVE", ["recovery-confirmer", "divergence-tracker"], "files", "proposed"),
    (
        "LEARN / PREVENT",
        [
            "postmortem-drafter",
            "factor-extractor",
            "action-item-gate",
            "action-item-chaser",
            "trend-analyst",
            "expiry-forecaster",
        ],
        "files",
        "proposed",
    ),
]
colw, gap = 166, 10
xx, yy = cx0, cy0 + 8
col_heights = [0, 0, 0, 0]
for i, (ph, items, kind, st) in enumerate(cat):
    col = i % 4
    h = 36 + 15 * len(items) + 4
    cy = yy + col_heights[col]
    comp(cx0 + col * (colw + gap), cy, colw, h, ph, items, kind=kind, st=st)
    col_heights[col] += h + 10
text(
    cx0,
    Y + 456,
    "SPEC §5.3 today: Metrics Analyst · Log Analyst · Change Auditor (planned personas) →",
    11,
    None,
    GREY,
)
text(
    cx0,
    Y + 472,
    "become saturation-finder · error-signature-summarizer · change-correlator above.",
    11,
    None,
    GREY,
)
comp(
    cx0,
    Y + 486,
    692,
    128,
    "Finding (B11) — the only thing that crosses an agent boundary",
    [
        "agent · hypothesis · evidence[] → evidence_refs[] (→ EvidenceRecord, proposed) · confidence · budget_spent",
        "+ artifact_ref (full result in recorder) · + open_questions[] — ≤2k tokens to the parent, never the trace",
        "Assignment (B11): agent · question · context_slice · budget — sub-agents are stateless",
    ],
    kind="audit",
    st="landed",
    tag=("BUILD", "+Hypothesis +Evidence typed"),
)

pkg(
    1480, Y, 660, 300, "knowledge/", "retrieve(ctx) → B3 · federates via mcp/, never its own client"
)
comp(
    1496,
    Y + 56,
    300,
    100,
    "facade.py",
    [
        "episodes + recipes + federated",
        "token + item budget → KnowledgeBundle",
        "source_ref + score per item",
        "graph_paths stays empty (post-v1)",
    ],
    st="planned",
    tag=("BUILD", ""),
)
comp(
    1808,
    Y + 56,
    316,
    100,
    "episodes (PostgresMemory)",
    [
        "pgvector · dimension fixed by owner",
        "valid_at / recorded_at bi-temporal",
        "supersede by insert, never delete",
        "as_of=T → replay belief at T",
    ],
    kind="store",
    st="planned",
    tag=("ADOPT", "pgvector"),
)
comp(
    1496,
    Y + 166,
    300,
    100,
    "recipes/*.yaml",
    [
        "Recipe{name, triggers.tags, steps, tools}",
        "trigger match on entity tags",
        "hand-authored; drafts/ post-v1 Distiller",
    ],
    kind="files",
    st="planned",
    tag=("COPY", "Robusta playbooks"),
)
comp(
    1808,
    Y + 166,
    316,
    100,
    "federated (stub) · embed",
    [
        "federated[] = [] until M5",
        "ModelProvider.embed → vector width check",
        "B8 embed_call recorded",
    ],
    st="planned",
    tag=("ADOPT", "langchain-mcp-adapters"),
)

pkg(1480, Y + 320, 660, 320, "governor/", "per AGENT FILE first, per run second · fails closed")
comp(
    1496,
    Y + 376,
    300,
    110,
    "budget.py + ledger.py",
    [
        "max_tool_calls · max_tokens · max_turns · timeout",
        "Decimal USD ledger in Postgres",
        "price table settings.model.prices",
        "unpriced prod model → boot failure",
        "breach → inconclusive w/ partial findings",
    ],
    st="planned",
    tag=("BUILD", "+ litellm completion_cost"),
)
comp(
    1808,
    Y + 376,
    316,
    110,
    "breaker.py",
    [
        "3 consecutive provider failures",
        "→ pause consumption 60s",
        "→ needs_human for open runs",
        "tests at 2 vs 3, pause −1s vs +1s",
    ],
    st="planned",
    tag=("ADOPT", "tenacity · purgatory"),
)
comp(
    1496,
    Y + 496,
    300,
    124,
    "scheduler.py (APScheduler)",
    [
        "registry sync tick",
        "approval-expiry sweep (30 min)",
        "recipe-driven scheduled investigations",
        "LEARN/PREVENT agents: daily · weekly · monthly",
        "emit ordinary B2 events",
    ],
    st="planned",
    tag=("ADOPT", "APScheduler 3.11"),
)
comp(
    1808,
    Y + 496,
    316,
    124,
    "storm_brake.py",
    [
        "queue lag > 25 → only critical|high dequeued",
        "tests at 25 vs 26",
        "worker max in-flight 3",
        "RPM/TPM limiter on provider",
    ],
    st="planned",
    tag=("COPY", "OnCall window step"),
)

# ── Row D · mcp / actions / recorder ──────────────────────────────────────
Y = 1300
pkg(
    60, Y, 1120, 400, "mcp/", "ONE client · ONE manifest · TWO enforcement points (ADR-0010, -0017)"
)
comp(
    76,
    Y + 56,
    250,
    110,
    "gateway.py — the only MCP client",
    [
        "FastMCP in-memory transport",
        "Client(server) same process",
        "federated: HTTPS + cert verify",
        "every call → B8 tool_call",
    ],
    st="planned",
    tag=("ADOPT", "langchain-mcp-adapters 0.3"),
)
comp(
    338,
    Y + 56,
    250,
    110,
    "manifest.yaml + loader",
    [
        "tool → tier (read | privileged)",
        "unknown tool / dup / no tier → boot fail",
        "registry tool absent → boot fail",
        "privileged set EMPTY in prod",
    ],
    kind="files",
    st="planned",
    tag=("BUILD", ""),
)
comp(
    600,
    Y + 56,
    250,
    110,
    "tiers.py — two checks",
    [
        "① on_call_tool middleware → ToolError",
        "② executor re-check before dispatch",
        "each proven to deny ALONE",
        "privileged → B5 interrupt",
    ],
    kind="gate",
    st="planned",
    tag=("ADOPT", "wrap_tool_call middleware"),
)
comp(
    862,
    Y + 56,
    302,
    110,
    "approvals.py — B5 broker",
    [
        "mint(binding) → 256-bit opaque token",
        "only sha stored · 30-min expiry",
        "consume = ONE atomic UPDATE (race-safe)",
        "expire sweep · Slack buttons · resume graph",
    ],
    kind="gate",
    st="planned",
    tag=("COPY", "HolmesGPT ApprovalRequirement"),
)
comp(
    76,
    Y + 176,
    250,
    104,
    "existing MCP servers (bindings only)",
    [
        "grafana/mcp-grafana → Prom · Loki · alerting · on-call",
        "Datadog MCP (hosted, 50 calls/10s) · k8s-mcp --read-only",
        "github-mcp-server · mcp.linear.app · prometheus-mcp",
    ],
    kind="port",
    st="planned",
    ls=9.5,
    tag=("CONSUME", "6 official servers"),
)
comp(
    338,
    Y + 176,
    250,
    104,
    "servers/ we still write (FastMCP 3.4)",
    [
        "knowledge.search / expand → knowledge.facade",
        "recipe.read → recipes/ · change.list → PlatformPort",
        "channel.post_thread · channel.ask_with_buttons",
        "testing/demo_destructive_noop (test config only)",
    ],
    st="planned",
    ls=9.5,
    tag=("BUILD", "no external MCP has these"),
)
comp(
    600,
    Y + 176,
    250,
    104,
    "federated/loader.py",
    [
        "descriptors/*.yaml: endpoint,",
        "tool_allowlist, prefix",
        "remote cannot widen surface",
        "same client · same manifest · same checks",
    ],
    st="planned",
    tag=("ADOPT", "MultiServerMCPClient"),
)
comp(
    862,
    Y + 176,
    302,
    104,
    "evidence_snapshot.py",
    [
        "EvidenceRecord{ref, tool, query, ts,",
        "result_sha256, snapshot_ref}",
        "written on EVERY witness read",
        "resolvable after vendor retention",
    ],
    kind="audit",
    st="proposed",
    tag=("BUILD", "13/14 products lack it"),
)
text(
    76,
    Y + 306,
    "witness ports — what an agent can see; 6 of 8 are bindings to the MCP servers above (COPY Keep BaseProvider shape), 2 in-process:",
    11.5,
    "700",
    "#0b7285",
)
wp = [
    "ChangeSource",
    "MetricSource",
    "LogSource",
    "TraceSource",
    "TopologySource",
    "IncidentHistorySource",
    "ExternalStatusSource",
    "ChatSource",
]
for i, n in enumerate(wp):
    inproc = n in ("ChatSource", "IncidentHistorySource")
    comp(
        76 + i * 137,
        Y + 316,
        132,
        78,
        n,
        ["in-process" if inproc else "→ MCP binding", "domain packs swap it"],
        kind="port",
        st="proposed",
        ts=10.5,
        ls=9.5,
        tag=("BUILD" if inproc else "CONSUME", ""),
    )

pkg(1200, Y, 400, 400, "actions/", "deterministic · no LLM · exactly one ticket per fingerprint")
comp(
    1216,
    Y + 56,
    368,
    118,
    "service.py",
    [
        "open_run() — ON CONFLICT (run_id) → state read",
        "apply() — FOR UPDATE run · read ticket_actions",
        "INSERT tickets ON CONFLICT (fp) WHERE closed_at IS NULL",
        "  → created | loser UPDATEs winner's ticket",
        "close_run() — status + conclusion + audit_end_offset",
    ],
    st="landed",
    tag=("KEEP", ""),
)
comp(
    1216,
    Y + 184,
    176,
    96,
    "ticket_actions ledger",
    ["(fingerprint, run_id) unique", "replayed:true on redelivery", "partial unique index 0003"],
    kind="store",
    st="landed",
    tag=("KEEP", ""),
)
comp(
    1408,
    Y + 184,
    176,
    96,
    "TicketingPort adapters",
    [
        "FixtureTicketing ✓",
        "LinearAdapter (GraphQL,",
        "inspect errors on 200) M2",
        "conformance suite",
    ],
    st="landed",
    tag=("CONSUME", "Linear MCP · gql"),
)
comp(
    1216,
    Y + 290,
    176,
    96,
    "channels/ (IR + adapters)",
    [
        "ir.py: Message/Section IR",
        "slack.py · discord.py · telegram.py",
        "root card edited in place",
        "thread only findings/approval",
    ],
    st="planned",
    tag=("ADOPT", "slack-bolt Socket Mode"),
)
comp(
    1408,
    Y + 290,
    176,
    96,
    "findings_writeback.py",
    ["PlatformPort.write_finding", "B10 · stub in v1"],
    st="planned",
    tag=("BUILD", ""),
)

pkg(
    1620,
    Y,
    520,
    400,
    "recorder/",
    "JSONL is the source of truth (ADR-0012) · Postgres only indexes",
    kind="audit",
)
comp(
    1636,
    Y + 56,
    244,
    118,
    "writer.py",
    [
        "audit-<date>T<time>-<pid>.jsonl",
        "fsync per line · monotonic seq",
        "byte offsets returned",
        "failures counter → /healthz",
        "read_run(run_id) → lines",
    ],
    kind="audit",
    st="landed",
    tag=("KEEP", ""),
)
comp(
    1892,
    Y + 56,
    232,
    118,
    "runs index (Postgres)",
    [
        "run_id → file + start/end offset",
        "status · conclusion jsonb",
        "GET /runs/{fp} reads it",
        "migration 0003",
    ],
    kind="store",
    st="landed",
    tag=("KEEP", ""),
)
comp(
    1636,
    Y + 184,
    244,
    96,
    "broadcast.py",
    [
        "in-process async channel",
        "publish after append (file first)",
        "feeds `logs --follow`",
        "seam for SSE later",
    ],
    kind="audit",
    st="planned",
    tag=("BUILD", ""),
)
comp(
    1892,
    Y + 184,
    232,
    96,
    "redaction",
    ["settings.redaction patterns", "runs before EVERY append", "credentials never in payload"],
    kind="audit",
    st="planned",
    tag=("BUILD", ""),
)
comp(
    1636,
    Y + 290,
    244,
    96,
    "replay.py",
    [
        "read run byte range",
        "feed recorded llm_call + tool_call",
        "→ RecordedModel + RecordedExecutor",
        "--live is explicit opt-in",
    ],
    kind="audit",
    st="planned",
    tag=("ADOPT", "vcrpy + @task cache"),
)
comp(
    1892,
    Y + 290,
    232,
    96,
    "B8 AuditEvent kinds",
    [
        "event · transition · llm_call",
        "tool_call · gate · action",
        "+ hypothesis · evidence (proposed)",
        "+ rejected · quarantined",
    ],
    kind="audit",
    st="landed",
    tag=("COPY", "FH events · Dispatch Event"),
)

# ── Row E · containers ────────────────────────────────────────────────────
Y = 1730
text(60, Y - 10, "BACKING CONTAINERS (compose services + volume)", 12, "700", GREY)
comp(
    60,
    Y,
    900,
    96,
    "postgres — pgvector/pgvector:0.8.1-pg16",
    [
        "tables (0001–0004): events · quarantine · runs · tickets · ticket_actions · outbox columns",
        "planned: episodes (0006) · langgraph checkpoints · approvals · spend_ledger · storm counters",
        "advisory lock per fingerprint · partial unique index open ticket per fp",
    ],
    kind="store",
    st="landed",
)
comp(
    980,
    Y,
    560,
    96,
    "redis:7.4-alpine — appendonly",
    [
        "stream agentevents (maxlen) · consumer group intelligence",
        "XINFO GROUPS → {lag, pending} on /healthz",
        "never the source of truth — the outbox is",
    ],
    kind="store",
    st="landed",
)
comp(
    1560,
    Y,
    580,
    96,
    "volume audit-logs:/app/logs",
    [
        "JSONL files · one per recorder start",
        "proposed: evidence snapshots beside it, content-addressed",
        "outlives `docker compose down`",
    ],
    kind="audit",
    st="landed",
)

# ── Row F · step ledger of one run ────────────────────────────────────────
Y = 1870
P(
    f'  <rect x="60" y="{Y}" width="2080" height="520" rx="10" fill="#fbfaff" stroke="#6741b8" stroke-width="1.4"/>'
)
text(
    76,
    Y + 28,
    "ONE RUN, STEP BY STEP — the smallest things that get reported",
    15,
    "700",
    "#6741b8",
)
text(
    76,
    Y + 46,
    "Each column is one reported step. Row 1: what the component does · Row 2: the B8 line it appends (kind) · Row 3: what the responder sees in the Slack thread / GET /runs · "
    "modelled on Cleric's activity-log rows, Grafana's hypothesis states + numbered citation chips, Datadog's validated / invalidated / inconclusive.",
    10.5,
    None,
    GREY,
)

steps = [
    (
        "1 admit",
        "receiver",
        ["verify → normalize", "fingerprint → dedupe", "or quarantine / 401"],
        "event | quarantined | rejected",
        ["202 accepted", "dedupe_count n"],
        "landed",
    ),
    (
        "2 enqueue",
        "outbox",
        ["commit row", "XADD → receipt", "retry if Redis down"],
        "transition: queued",
        ["queue lag on /healthz"],
        "landed",
    ),
    (
        "3 claim run",
        "worker",
        ["run_id = event id", "ON CONFLICT → state", "audit start offset"],
        "transition: run.open",
        ["🧵 “Investigating <title>”", "run_id"],
        "landed",
    ),
    (
        "4 route",
        "workflows",
        ["pick workflow by kind", "effort ladder by sev", "≤2 / ≤4 / ≤8 agents"],
        "transition: workflow",
        ["“scope: N agents,", "budget $X”"],
        "proposed",
    ),
    (
        "5 retrieve",
        "knowledge",
        ["episodes + recipes", "under token budget", "source_ref + score"],
        "transition: retrieve (B3)",
        ["“2 precedents,", "1 runbook” chips"],
        "planned",
    ),
    (
        "6 plan",
        "supervisor",
        ["WHICH agents", "context_slice each", "hypotheses seeded"],
        "llm_call plan · hypothesis: open",
        ["hypothesis board:", "H1 open · H2 open"],
        "planned",
    ),
    (
        "7 agent start",
        "agent_runner",
        ["load spec · prompt sha", "skills preloaded", "input validated"],
        "transition: agent.start",
        ["“↳ change-correlator", "running”"],
        "planned",
    ),
    (
        "8 witness read",
        "mcp.gateway",
        ["tier check ×2", "query vendor", "snapshot result"],
        "tool_call + evidence (proposed)",
        ["citation chip [1]", "query · ts · sha"],
        "planned",
    ),
    (
        "9 model turn",
        "ports.model",
        ["prompt_ref + sha", "usage · latency", "Decimal cost"],
        "llm_call",
        ["cost so far $0.0x", "turn k / max"],
        "planned",
    ),
    (
        "10 finding",
        "agent_runner",
        ["output validated", "evidence_ref per claim", "artifact_ref"],
        "finding (B11)",
        ["“deploy #412 landed", "4m before onset [1][2]”"],
        "planned",
    ),
    (
        "11 board",
        "hypothesis_board",
        ["H1 → validated", "H2 → invalidated", "H3 inconclusive"],
        "hypothesis: state change",
        ["board updated", "✓ ✗ ?"],
        "proposed",
    ),
    (
        "12 verify",
        "verify agents",
        ["disproof attempted", "temporal order ok?", "gate root_caused"],
        "gate: verify",
        ["“tried to disprove H1:", "no counter-evidence”"],
        "proposed",
    ),
    (
        "13 conclude",
        "synthesize",
        ["B6 status + confidence", "summary_md · actions", "tokens · wall_ms"],
        "conclusion (B6)",
        ["status · confidence", "findings · next steps"],
        "planned",
    ),
    (
        "14 act",
        "actions",
        ["ticket create | update", "(fp, run_id) ledger", "receipt"],
        "action",
        ["“opened SMOKE-… ” or", "“updated (#3)”"],
        "landed",
    ),
    (
        "15 close",
        "worker",
        ["audit end offset", "status concluded", "XACK after commit"],
        "transition: run.close",
        ["GET /runs/{fp}", "audit byte range"],
        "landed",
    ),
]
sx, sy = 76, Y + 84
colw = 128
for i, (name, who, does, kind, sees, st) in enumerate(steps):
    x = sx + i * (colw + 9)
    fill, stroke, ink = C["audit"] if st != "landed" else C["core"]
    P(
        f'  <rect x="{x}" y="{sy}" width="{colw}" height="290" rx="6" fill="#ffffff" stroke="{stroke}"/>'
    )
    status_dot(x + 12, sy + 16, st)
    text(x + 22, sy + 20, name, 12, "700", ink)
    text(x + 8, sy + 36, who, 10, None, GREY)
    yy = sy + 56
    for ln in does:
        text(x + 8, yy, ln, 10, None, INK)
        yy += 13
    P(f'  <line x1="{x}" y1="{sy + 100}" x2="{x + colw}" y2="{sy + 100}" stroke="#d5dde5"/>')
    text(x + 8, sy + 116, "B8:", 9.5, "700", "#6741b8")
    # wrap kind at ~20 chars
    words, line, lines_k = kind.split(), "", []
    for wd in words:
        if len(line) + len(wd) + 1 > 20:
            lines_k.append(line)
            line = wd
        else:
            line = (line + " " + wd).strip()
    lines_k.append(line)
    yy = sy + 130
    for ln in lines_k:
        text(x + 8, yy, ln, 10, None, "#2f1e5c")
        yy += 13
    P(f'  <line x1="{x}" y1="{sy + 172}" x2="{x + colw}" y2="{sy + 172}" stroke="#d5dde5"/>')
    text(x + 8, sy + 188, "sees:", 9.5, "700", "#0b7285")
    yy = sy + 202
    for ln in sees:
        text(x + 8, yy, ln, 10, None, "#0b3a42")
        yy += 13
    if i < len(steps) - 1:
        arrow(x + colw, sy + 145, x + colw + 9, sy + 145)
# loop annotation over 7–10
lx1, lx2 = sx + 6 * (colw + 9), sx + 10 * (colw + 9) - 9
P(
    f'  <path d="M{lx1} {sy - 8} L{lx1} {sy - 16} L{lx2} {sy - 16} L{lx2} {sy - 8}" fill="none" stroke="#6741b8" stroke-width="1.2"/>'
)
text(
    (lx1 + lx2) / 2,
    sy - 21,
    "repeats per agent (∥ across agents) and per turn within an agent, bounded by governor budget",
    10.5,
    None,
    "#6741b8",
    "middle",
)
# side paths
by = sy + 310
comp(
    76,
    by,
    672,
    92,
    "budget / provider failure path",
    [
        "governor breach or breaker open → synthesize inconclusive | needs_human",
        "with partial findings → B8 gate: budget → ticket still filed",
        "a run never dies silently (§5.7); XACK only after that Conclusion is durable",
    ],
    kind="gate",
    st="planned",
)
comp(
    764,
    by,
    672,
    92,
    "privileged action path (M5)",
    [
        "mitigation-ranker draft → B5 ApprovalRequest → Slack buttons → interrupt",
        "persists across restart → consume token ONCE → act → mitigation-verifier",
        "B8: gate approval.requested · approval.decided · action · gate verified → mitigated",
    ],
    kind="gate",
    st="planned",
)
comp(
    1452,
    by,
    672,
    92,
    "healthy-system path (no-fault eval)",
    [
        "flapping monitor → every agent returns empty candidates → board all inconclusive",
        "→ verify has nothing to validate → B6 inconclusive, explicit “no change / no saturation”",
        "ticket updated, not opened · this run IS the no-fault eval case (12/14 products lack one)",
    ],
    kind="audit",
    st="proposed",
)

# ── cross-row arrows (primary path only, to stay legible) ─────────────────
arrow(400, 242, 400, 270, "B1 verified inbound", bold=True, lx=470, ly=262)
arrow(780, 380, 800, 380, "B2", bold=True)
arrow(990, 600, 990, 630, "B2 → engine", bold=True, lx=1060, ly=622)
arrow(560, 1270, 560, 1300, "B4 ToolCall", bold=True, lx=620, ly=1292)
arrow(1400, 1000, 1200, 1000, None)
text(1300, 992, "B6 Conclusion — determinism boundary", 10.5, None, GREY, "middle")
arrow(1200, 1000, 1200, 1300, None, bold=True)
arrow(1460, 690, 1480, 690, None, dashed=True)
text(1470, 680, "B3", 10.5, None, GREY, "middle")
arrow(1460, 1000, 1480, 1000, "budget", dashed=True)
arrow(1600, 1500, 1620, 1500, "B8 action", dashed=True)
arrow(1180, 1500, 1200, 1500, None, dashed=True)
arrow(600, 1700, 600, 1708, None, dashed=True)
P(
    '  <line x1="600" y1="1708" x2="1880" y2="1708" stroke="#6741b8" stroke-width="1.3" stroke-dasharray="6 4"/>'
)
arrow(1880, 1708, 1880, 1700, None, dashed=True)
text(
    1240,
    1704,
    "B8 — every node, llm_call, tool_call, gate, action, evidence → recorder",
    10.5,
    None,
    "#6741b8",
    "middle",
)

P("</svg>")
from pathlib import Path

open(Path(__file__).resolve().parent.parent / "system" / "c3-components.svg", "w").write(
    "\n".join(out)
)
print("ok", len("\n".join(out)))
