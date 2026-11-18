# KCR-02A | LightRAG and HippoRAG graph-retrieval technique audit

**Research status:** pinned source reviewed; dependency-free **synthetic** comparative test proposed. **No production selection, backend connection or user-data benchmark.**
**Review date:** 2026-11-17. **KAREN architecture:** [MemoryRuntimeManager](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/memory_runtime_manager.py), [NeuroRecall](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/retrieval/neuro_recall.py).

## What we found in actual upstream implementations

### HippoRAG 2
[HippoRAG 2 at d5c8329, `HippoRAG.py` lines 2012–2122](https://github.com/OSU-NLP-Group/HippoRAG/blob/d5c8329422e0a0b834a15874545cb6a74b4f9b26/src/hipporag/HippoRAG.py#L2012-L2122):
- Links subjects and objects of retrieved facts to graph entities. The fact score is divided by the entity's source-chunk count before aggregation, reducing repeated/source-heavy entity influence.
- Seeds passage nodes with normalized dense-retrieval scores scaled by a `passage_node_weight`.
- Adds entity and passage seed weights and calls a graph walk; later maps scores back to passage IDs.
- [`run_ppr` lines 2177–2219](https://github.com/OSU-NLP-Group/HippoRAG/blob/d5c8329422e0a0b834a15874545cb6a74b4f9b26/src/hipporag/HippoRAG.py#L2177-L2219) uses **weighted, undirected Personalized PageRank** with `igraph`, using configurable damping (0.5 default in method signature).
- [Incremental weighted edge merging and source lineage](https://github.com/OSU-NLP-Group/HippoRAG/blob/d5c8329422e0a0b834a15874545cb6a74b4f9b26/src/hipporag/HippoRAG.py#L1545-L1676) explicitly requires typed provenance; merges duplicate edge contributions rather than creating parallel edges.

**Portable research idea:** Apply *independent* weighted random-walk-with-restart over KAREN's authorized, already-bounded graph neighbors. No external graph store or embedding manager. This is a general mathematical algorithm, not copied upstream code.

### LightRAG
[LightRAG `base.py`](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/lightrag/base.py) distinguishes local, global, hybrid, mix, naive and bypass query modes; [`operate.py`](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/lightrag/operate.py) controls extraction, graph and chunk candidate selection, source limits and context budgets.
- **local** searches entity-oriented context; **global** searches relationships; **hybrid** combines the two; **mix** also uses vector-retrieved text chunks. The returned source references matter more than the mode labels.
- Source-aware incremental relationship rebuild [lines 1138–1445](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/lightrag/operate.py#L1138-L1445) explicitly logs missing or unusable extraction caches rather than treating a partial rebuild as perfect.
- [Query cache identity around lines 4915–4990](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/lightrag/operate.py#L4915-L4990) includes source-context selection and token budget settings; changing a context budget must not return stale citations/references.
- Its [native PostgreSQL graph storage](https://github.com/HKUDS/LightRAG/blob/264b00ebfac646b8366966f4705e36423088dc51/lightrag/kg/pgtable_impl.py) and Apache AGE alternative do **not** justify adding a second KAREN schema.

**Portable research ideas:** source-aware context selection, candidate budgeting, rebuild integrity, and cache-key provenance. KAREN's current graph retrieval and evidence selection remain owned by NeuroRecall / PostgreSQL.

## KAREN native baseline

[SpreadingActivation](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/associative/spreading_activation.py) propagates a fixed decay per hop and takes the maximum activation along paths; it does not apply per-edge evidence strength. This can tie relevant and distracting nodes that share hop distance.

[PostgresGraphRepository](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/platform/memory/postgres/graph_repository.py) already traverses bounded relationships under tenant/user, temporal-validity and consent checks. A research PPR experiment **must not** fetch its own unscoped graph or become a persistence owner.

## Independent reference experiment

[`test_associative_rank_research.py`](../../../tests/benchmarks/memory/test_associative_rank_research.py) compares a pure-Python weighted undirected random walk with the actual KAREN `SpreadingActivation` primitive, on **synthetic fixed graphs**.

- Tests a known two-node stationary distribution; mass conservation; deterministic convergence; iteration/node bounds; invalid input; graph cycles; explicit scoped synthetic filtering; revocation and recomputation.
- Demonstrates only that **edge weights can break same-hop ties**. Any synthetic difference is *not* general retrieval improvement, real-world security evidence, or a recommendation to deploy PPR.
- PPR benchmark uses no new runtime packages and does not import `networkx`, `igraph`, HippoRAG or LightRAG.
- Real user evidence, cross-tenant reads, embeddings, actual PostgreSQL graph neighborhoods, source ACL verification and p95 are **unproven**.

## Adversarial next gates
1. Confirm provenance-linked graph edge **weights** are trustworthy and comparable. Do not multiply confidence from repeated or stale source IDs.
2. Compare PPR against existing spreading activation across independently labeled 2–5-hop graphs, high-degree hub distractors, disconnected subgraphs and mixed valid-time/known-time snapshots.
3. Only feed PPR neighborhoods returned through the canonical scoped and consent-aware graph data path; source-ACL verification must be live, not persisted `authorized=true` metadata.
4. Preserve original NeuroRecall rejection/fusion/selection behavior. Absent authorization, score computation must not release additional memories.
5. Measure p50/p95/p99, allocation count, CPU, overall memory, score stability, degradation/abstention and marginal quality at identical budgets.
6. Do not copy or install a framework. If an algorithm truly wins, adapt it into the existing canonical component under a separate review/ADR.

## Cost and licensing
Direct manifests show HippoRAG pins `torch==2.5.1`, `igraph==0.11.8`, `openai>=3.3.1`, while KAREN pins `openai==2.32.0`. LightRAG pulls its own vector/graph/storage + LLM libraries. A pure-Python research probe avoids these packages and model downloads. Licenses: HippoRAG MIT, LightRAG MIT, according to their pinned upstream LICENSE files.

**Decision:** Continue source study, retain KAREN's current runtime algorithm. No framework, PPR algorithm, graph backend or new package is approved for production.

## CI execution gate
The Main Quality backend job explicitly invokes this research fixture and the two earlier KCR-01 memory probes, as well as KAREN's original spreading-activation tests. Green status is not equivalent to real database or model benchmarks. **Pending** exact-head check execution on this research branch; no pass is assumed in advance.
