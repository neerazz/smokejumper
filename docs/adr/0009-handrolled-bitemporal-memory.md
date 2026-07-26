# ADR-0009: Hand-rolled bi-temporal memory behind MemoryPort; Graphiti rejected, Cognee deferred

**Status:** Accepted · 2026-07-10 · **Level:** L2 · **Narrowed** 2026-07-26 (v1 ships `episodes`
only; edge tables and traversal are post-v1 — see "Narrowed for v1" below)

## Context
Knowledge needs GraphRAG (vectors find entry points, graph expands) with bi-temporal truth
(what was valid when vs what we believed when) for honest incident replay. Deep research
verified: Graphiti (28k★, best-in-class bi-temporal model) runs only on Neo4j/FalkorDB/
Neptune — incompatible with ADR-0002. Cognee (27k★) verifiably runs GraphRAG on a single
Postgres, with bi-temporal as a recent opt-in mode; LightRAG similar, weaker temporal story.

## Decision
Hand-roll the store: Postgres edge/node tables copying **Graphiti's published bi-temporal
data model** (valid_at/invalid_at + created_at/expired_at, pgvector embeddings), behind a
`MemoryPort`.

## Narrowed for v1 (2026-07-26)
The blueprint choice stands; the scope shrank. v1 implements `episodes` only — pgvector
similarity over closed cases, carrying `valid_at`/`recorded_at`, so the bi-temporal property
this record exists to protect is present from the first migration. `kg_nodes`/`kg_edges` and
≤2-hop traversal are post-v1 behind the same `MemoryPort`.

Why: nothing in v1 writes edges. The Distiller, the only component specified to propose them,
is also deferred, so a v1 graph would be traversed empty on every retrieval. Shipping the
tables first would have meant maintaining a schema, migrations, and a query path for a store
with no writer. Adding them later is a migration plus an adapter method, not a redesign — which
is the property `MemoryPort` was introduced for.

## Options considered
1. **Hand-roll on Graphiti's schema (chosen)** — steal the data model, not the dependency.
2. Adopt Cognee — most capability per line of code, but dev-tagged releases, recent/opt-in
   bi-temporal, and a large extraction pipeline we'd depend on for audit-critical truth.
3. Adopt Graphiti + accept a second DB — best temporal semantics, breaks ADR-0002.
4. mem0 — graph memory moved out of core OSS; Postgres path needs the Apache AGE extension;
   analyst-flagged relicense risk. Rejected.

## Trade-offs accepted
- **We gave up** free entity extraction, dedup, and graph reasoning (Cognee's real value) —
  whatever eventually writes edges has to earn its keep by hand.
- **We accepted** owning schema + retrieval quality: our GraphRAG will start dumber than
  Cognee's out of the box.
- **We kept** a deterministic, version-stable schema for the component whose correctness IS
  the product's credibility, on the one Postgres we already run. Red-team verdict: for an
  SRE tool, schema stability beats capability at HEAD.

## Revisit when
A pinned-version Cognee spike (planned, ~1 day) confirms its temporal mode fits — then it
becomes a MemoryPort adapter, competing on eval numbers, not vibes.
