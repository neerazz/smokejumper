# Architecture diagrams

Three kinds of diagram, one folder each. Every diagram answers one question, named in its
header. `SPEC.md` is normative; a diagram that disagrees with it is stale and is fixed in the same
change. Hand-laid SVGs are generated from `_gen/` so they can be regenerated exactly; Mermaid
sources render through `scripts/render_architecture.py`.

## `system/` — what the software is

| File | Level | Question it answers | Status | Regenerate |
|---|---|---|---|---|
| `c2-containers.svg` (`.mmd`) | C4 L2 | What are the blocks, the B1–B11 contracts between them, and which are core vs ports? | **canonical**, agrees with SPEC | `python3 scripts/render_architecture.py` |
| `c2-components.svg` | C4 L2 | Layered component view of the v1 design | canonical, hand-maintained | edit SVG |
| `c3-components.svg` | C4 L3 | Every component inside the `app` container by package, with landed / planned / proposed status, a reuse tag (ADOPT / CONSUME / COPY / BUILD / KEEP) per box, and the step ledger of one run | current + proposed | `python3 architecture/_gen/c3_components.py` |
| `proposed-atomic-agents.svg` (`.mmd`) | C4 L2 | If agents are questions not roles, what are the layers and where do the gates sit? | **proposed** — pre-plan only | `python3 scripts/render_architecture.py architecture/system/proposed-atomic-agents.mmd` |

## `journeys/` — what a person experiences

| File | Question | Regenerate |
|---|---|---|
| `j1-oncall-responder.svg` | From page to closed ticket without leaving Slack: what does the responder see, decide, approve? | `python3 architecture/_gen/journeys.py` |
| `j2-operator-setup.svg` | From clone to first investigated alert: how many steps, credentials, and proofs? | same |

## `scenarios/` — what the system must witness and conclude

Each scenario is grounded in named public postmortems (sources in the diagram footer) and shows,
minute by minute: the system signals in the order they appear, the hypotheses an investigator
holds, the evidence that validates or kills each, and the mitigation ladder by reversibility.

| File | Scenario | Why it is in the set |
|---|---|---|
| `s1-db-iops-saturation.svg` | API 5xx from database IOPS saturation (burst-balance exhaustion → latency → pool exhaustion) | the classic slow-burn cause hidden behind an application symptom |
| `s2-bad-deploy-rollback.svg` | Bad deploy / config change → error spike → rollback | the most common cause in public postmortems; tests change-correlation and reversible action |
| `s3-connection-pool-exhaustion.svg` | Pool / thread exhaustion from traffic surge or slow downstream | tests saturation-finder vs change-correlator disambiguation |
| `s4-upstream-dependency-outage.svg` | Vendor / cert / DNS outage | tests "ours or theirs" and the not-actionable verdict |

Regenerate all four: `python3 architecture/_gen/scenarios.py`.

## `_gen/` — generators

`swimlane.py` (shared renderer) · `journeys.py` · `scenarios.py` · `c3_components.py`.
Rasterize any SVG for review with headless Chrome:
`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --screenshot=out.png --window-size=W,H file://$PWD/<svg>`.
