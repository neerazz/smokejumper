# ADR-0003: No LLM in Receiver or Actions; B6 determinism boundary

**Status:** Accepted · 2026-07-10 · **Level:** L1

## Context
An SRE bot sits between noisy alert firehoses and consequential outputs (tickets, Slack,
eventually remediations). Model calls are nondeterministic, slow, and costly; the failure
modes at the edges (duplicate tickets, hallucinated actions) destroy trust fastest.

## Decision
The ingress edge (Receiver: normalize/fingerprint/dedupe/coalesce) and the egress edge
(Actions: create-vs-update, receipts) are pure deterministic code. Models run only inside
the Intelligence block, and everything downstream of the B6 `Conclusion` contract is
model-free.

## Options considered
1. **Deterministic edges (chosen).**
2. LLM-assisted ingress (semantic dedupe/severity inference) — smarter grouping, but storm
   costs scale with alert volume and dedupe becomes non-reproducible.
3. Agent acts directly via tools (no Actions block) — fewer moving parts, but idempotency
   and audit become prompt-dependent.

## Trade-offs accepted
- **We gave up** semantic alert grouping at ingest ("these 3 differently-named alerts are
  the same incident") — fingerprints are syntactic; cross-alert correlation must happen
  inside Intelligence, after the queue.
- **We gave up** flexible, situation-specific output formatting — Actions render from the
  structured Conclusion only.
- **We kept** reproducibility (same webhook ⇒ same event ⇒ same ticket key), bounded cost
  under alert storms, and an egress the audit log can fully explain.

## Revisit when
Evidence shows fingerprint-miss duplicates are a top complaint — then add a *bounded*
similarity check at ingest (embedding distance, still no generation).
