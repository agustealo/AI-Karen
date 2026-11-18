# LightRAG | graph-informed retrieval without adopting its runtime

**Upstream:** [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) · **Pinned:** `264b00ebfac646b8366966f4705e36423088dc51` · **License/Python:** MIT; >=3.11 from [manifest](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/pyproject.toml) · **Status:** source-inspected, unbenchmarked.

## Functional mechanisms to reverse-engineer
1. Graph-informed **local** (neighbor entity), **global** (relationship) and **hybrid/mix** retrieval: identify how query entities and relations alter candidate coverage, not just answer synthesis.
2. Incremental entity/relation extraction, normalization, dedup, source chunk lineage, and graph rebuild when source documents change.
3. Native [`PGTableGraphStorage`](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/lightrag/kg/pgtable_impl.py) with indexed relational graph nodes and edges, JSONB payloads, advisory locks and bounded traversal (alternative to Apache AGE).
4. Query-context packing, chunk provenance, token limits and retry/degradation handling in [`operate.py`](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/lightrag/operate.py).

## KAREN overlap and possible value
- KAREN already has [PostgresGraphRepository](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/platform/memory/postgres/graph_repository.py), source event graph projection, entity resolver and **NeuroRecall as recall authority**.
- Study **candidate generation and source-aware packing**, not a new KV/vector/graph backend.
- Compare native graph and retrieval heuristics against current PostgreSQL graph + conditional pgvector/FTS, preserving the same source IDs, user/tenant and consent constraints.

## Dependency/deployment consequences
LightRAG base pulls in networkx, nano-vectordb, google-genai, json_repair, pypinyin and more. Its broad optional extras can add vector stores and other databases. Native Postgres graph mode removes need for AGE **in that product**, but installing the package still duplicates major responsibilities here. No production install approved.

## Investigation steps
- [ ] Inspect `kg/pgtable_impl.py` schema, edge identity, retry/advisory lock, tenant/workspace isolation and deletion behavior; contrast with Karen's `memory_relation` scoped SQL.
- [ ] Trace retrieval modes from `operate.py` into native candidate generation, token accounting and source lineage.
- [ ] Evaluate change/retraction replay behavior; no stale graph edges on deletion.
- [ ] Independently specify a **small algorithmic experiment** under NeuroRecall, without LightRAG runtime import.
- [ ] Test R01/R02/R03/R08/R09/R12/R14 from [benchmark contract](../BENCHMARK_CONTRACT.md).

**Gate:** Reject a second graph schema/storage owner. A useful technique must outperform KAREN's native retrieval and preserve all governance.

