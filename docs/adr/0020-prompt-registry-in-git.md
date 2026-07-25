# ADR-0020: Prompts live in git as immutable versions; every LLM call records prompt ref + sha256

**Status:** Accepted · 2026-07-25 · **Level:** L2

## Context
Prompts were specified inline in the Agent Registry: `{name, version, prompt, tools[],
budget{}, dispatch{triggers}}` (SPEC §5.3). That has four problems, one of which is serious.

1. **One file changes for two unrelated reasons.** A prompt rewrite and a tool-allowlist change
   land in the same YAML, so reviewing "what changed about this agent's behavior" means
   reading past its configuration.
2. **Multi-line YAML strings diff badly.** Prompt edits — the highest-leverage change anyone
   makes to this system — are the hardest thing in the repo to review.
3. **No supervisor prompts have a home at all.** `plan` and `synthesize` are model calls with no
   registry entry; their prompts had nowhere to live.
4. **The serious one: a recorded run cannot be attributed to a prompt.** The Flight Recorder
   captures `llm_call` payloads, but nothing stamps *which prompt version* produced them. So a
   regression cannot be traced to a prompt change, and replay cannot assert it is running the
   same prompt it recorded — silently invalidating the determinism ADR-0012 was built for.

Platform prompt registries (Langfuse, LangSmith, Phoenix playground) solve 1–3 with a nice UI
and runtime `get_prompt()` fetch.

## Decision
**`prompts/` in git is the single source of truth**, with immutable versioned files:

```
prompts/
├── supervisor/{plan,synthesize}/v<N>.md
├── agents/<agent-name>/v<N>.md
└── CHANGELOG.md
```

The registry references rather than inlines: `prompt: agents/metrics-analyst@v3`.

Three rules make it load-bearing:

- **Versions are immutable.** Never edit `v3`; add `v4`. Same discipline as "supersede, don't
  edit" for ADRs.
- **B8 `AuditEvent` gains `prompt_ref` and `prompt_sha256` on every `llm_call`.** Regressions
  become attributable, and replay asserts prompt identity instead of assuming it.
- **A prompt change requires an eval run** before merge. Prompts are behavior; behavior needs
  a regression gate.

A platform prompt playground (ADR-0019) may be used for *experimentation*. It is never the
store, and it never serves prompts at runtime.

## Options considered
1. **Git as source of truth, content-addressed in the recorder (chosen).**
2. Keep prompts inline in the registry (status quo) — fewest files, but leaves all four
   problems, including unattributable regressions.
3. Langfuse/LangSmith prompt management as the runtime source — best authoring UX by a wide
   margin, and label-based promotion is genuinely nice. **Rejected because it puts
   behavior-defining artifacts inside a third-party service's database**, which contradicts
   ADR-0012's governing rule that no platform owns the record. It also means prompts stop being
   code-reviewed, stop being bisectable, and a platform outage or wipe becomes a behavior
   change. This is the same reasoning that keeps the audit log in JSONL.
4. Prompts in the database with a migration per change — versioning without git's review
   tooling, and the audit trail lives in the thing being audited.
5. Prompts as Python string constants — diffable and trivially testable, but "adding an agent is
   config, not code" (SPEC §5.3) stops being true, and non-engineers can't touch them.

## Trade-offs accepted
- **We gave up** the platform authoring UX: no click-to-edit, no label-based promotion without
  a commit, no non-engineer editing without a PR. For a single-maintainer tool where every
  prompt change should be reviewed anyway, that is a fair price — and it would be the wrong
  trade for a product with prompt-writing PMs.
- **We accepted** immutable versions accumulating files over time, and the discipline of never
  editing a shipped version.
- **We accepted** that `prompt_sha256` makes a whitespace-only edit look like a behavior change.
  That is intentional: whitespace can change tokenization, and a false positive here is far
  cheaper than a silent one.
- **We kept** prompts reviewable as diffs, bisectable with `git bisect`, attributable from any
  recorded run, and assertable during replay — and the audit record stays free of any platform.

## Revisit when
Someone who is not an engineer needs to iterate on prompts daily (→ mirror `prompts/` into a
platform registry, with git still authoritative and a sync check in CI), or prompt count grows
past the point where a flat per-agent directory is navigable.
