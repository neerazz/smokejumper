# ADR-0002: One Postgres 16 + pgvector for all state

**Status:** Accepted · 2026-07-10 · **Level:** L1

## Context
The system needs: relational state (runs, approvals, tickets), vector search (episodic
memory), a knowledge graph (caused_by/fixed_by/applies_to), and LangGraph checkpoints.
Each has a specialized best-of-breed store (Neo4j, Qdrant/Weaviate, etc.).

## Decision
Every durable byte lives in one Postgres 16 instance: pgvector for embeddings, plain edge
tables for the graph, LangGraph's Postgres checkpointer, alembic-managed schema.

## Options considered
1. **Unified Postgres (chosen)** — 2026 consensus for this scale ("teams consolidating on
   Postgres+pgvector unified stores over separate graph DBs").
2. Postgres + Neo4j/FalkorDB — native graph algorithms and traversal speed; unlocks Graphiti.
3. Postgres + dedicated vector DB — better ANN recall/latency at large scale.

## Trade-offs accepted
- **We gave up** native graph traversal performance and algorithms (PageRank, community
  detection); ≤2-hop expansion in SQL is fine, deep analytics is not.
- **We gave up** Graphiti as an adoptable dependency (ADR-0009) — its backends are graph
  DBs only. This was the single most expensive consequence of this ADR.
- **We kept** transactional joins across memory/runs/audit index, one backup story, one
  connection pool, and a docker-compose a newcomer can run in one command.

## Revisit when
Graph queries need >2 hops routinely, or vector corpus growth degrades pgvector beyond
HNSW tuning. Escape hatch exists: MemoryPort (ADR-0009) isolates the store.
