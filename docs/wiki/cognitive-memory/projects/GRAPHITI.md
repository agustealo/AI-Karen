# Graphiti | episodic and bi-temporal truth handling

**Upstream:** [getzep/graphiti](https://github.com/getzep/graphiti) · **Pinned:** `4ef979c74e1e68d08217cf0af4022ddbc89c257f` · **License/Python:** Apache-2.0; >=3.10 · **Manifest:** [pyproject](https://github.com/getzep/graphiti/blob/4ef979c74e1e68d08217cf0af4022ddbc89c257f/pyproject.toml) · **Status:** source-inspected, unbenchmarked.

## Functional mechanisms to reverse-engineer
1. Convert conversational **episodes** into entity facts and edges, with source episode lineage.
2. Detect evidence changes and invalidate/supersede conflicting facts while retaining historical auditability.
3. Temporal fact search and cross-episode reconciliation; investigate valid time vs system-recorded time and late-arriving claims.
4. Combine text, embedding and graph traversal candidate sources; inspect optional rerankers in [search implementation](https://github.com/getzep/graphiti/blob/4ef979c74e1e68d08217cf0af4022ddbc89c257f/graphiti_core/search/search.py).
5. Episode ingest, group scope, dedup and source tracking in [Graphiti engine](https://github.com/getzep/graphiti/blob/4ef979c74e1e68d08217cf0af4022ddbc89c257f/graphiti_core/graphiti.py).

## KAREN overlap and possible value
- KAREN already has `MemoryTemporalEvolutionService`, `BeliefResolution`, `MemoryEpisode`, current-validity graph filters, and governed source events.
- Gap to prove: full `valid_at` **and** `known_at` query semantics after late corrections, including rollback/erasure, through NeuroRecall.
- Reproduce a temporal reconciliation **contract and test corpus**, not a second episode store.

## Dependency/deployment consequences
Graphiti's core package includes `neo4j>=5.26.0` and `posthog`; typical deployment requires a graph server (Neo4j/FalkorDB/Neptune), and default inference and embedding clients are OpenAI-based unless overridden. Defaults must be checked for egress and telemetry in isolated research. This exceeds Karen's zero-extra-service budget.

## Investigation steps
- [ ] Read temporal edge validity and `group_id`/scope handling; identify every default LLM/model call.
- [ ] Model T1 effective fact learned at T2, then amended at T3 with backdated evidence; ensure current/history queries do not invent data.
- [ ] Compare Graphiti-style episode provenance to KAREN's source-event/claim links.
- [ ] Test consent revocation and derived graph invalidation through R05/R06/R07/R08/R09/R14.
- [ ] Do not import graph drivers, servers or agent MCP service into KAREN.

**Gate:** KAREN temporal authority stays native; a new graph DB is unjustified unless a later ADR proves a gap that native PostgreSQL cannot close economically.

