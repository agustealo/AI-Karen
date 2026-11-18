# KAREN canonical capability baseline

**Snapshot:** `6b70128174aa76f8eda3700d9079f73a1849b62a` on 2026-11-17. This describes checked-in source, **not a live host health report**.

## What runtime actually composes
[MemoryRuntimeManager](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/core/memory/memory_runtime_manager.py) constructs:
- `RedisSTMAdapter` for STM;
- `NeuroRecall` with `PostgresRecallRetriever`, `PostgresProfileRecallRetriever`, `PostgresUserStateRecallRetriever`, `PostgresProceduralRecallRetriever`, and a bounded `HybridRetrievalRouter`;
- `PostgresEventSource`, `PostgresEntityResolver` and `LeanGraphService` backed by `PostgresGraphRepository`;
- `MemoryFormationService`, `PostgresNeuroVault`, and approved STM/graph projection workers.

Source paths:
- [NeuroRecall](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/core/memory/retrieval/neuro_recall.py)
- [PostgreSQL durable recall](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/platform/memory/postgres/recall_retriever.py)
- [PostgreSQL graph repository](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/platform/memory/postgres/graph_repository.py)
- [Graph projection](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/core/memory/graph/service.py)
- [Entity resolver](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/platform/memory/postgres/entity_resolver.py)

## Evidence inventory
| Capability | Current owner / behavior | Confidence and gap |
| --- | --- | --- |
| Governed memory writes | NeuroVault via canonical PostgreSQL session; formation and projection only after approved commit | WIRED; verify live commit, retry, deletion and projection consistency |
| STM/episodic context | Redis adapter, episode segmentation, governed durable events | WIRED; verify restart and bounded degradation |
| Durable lexical recall | `PostgresRecallRetriever` uses SQLAlchemy `content.contains(term)`, then confidence/recency sorting | **INSPECTED**; this method is not native PostgreSQL full-text search |
| Semantic vector recall | Docs describe pgvector; runtime diagnostics label storage `postgres_pgvector_fts` | **UNPROVEN on this production read path**; verify real vector SQL and actual score provenance before claiming |
| Graph retrieval | PostgreSQL recursive CTE with tenant/user predicates, current-validity and consent checks; entity cue resolution uses pg_trgm similarity | WIRED; retrieval behavior needs live DB proof |
| Temporal facts | [MemoryTemporalEvolutionService](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/core/memory/temporal/service.py) handles reinforce, coexist, supersede, contradict; graph edges have valid/observed/recorded time | INSPECTED and unit-tested; end-to-end dual-clock as-of query unproven |
| Contradiction | [BeliefResolution](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/core/memory/belief_resolution.py) and belief contradiction detector | INSPECTED; consistency of projections, graph and user-visible historical answers unproven |
| Associative recall | [SpreadingActivation](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/core/memory/associative/spreading_activation.py) uses bounded local graph + decay | Unit-tested; production graph-neighborhood composition unproven |
| Decision lineage | [OutcomeRecorder](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/core/runtime/outcome/recorder.py) and governed outcomes; runtime decision metadata | WIRED pieces; cross-system why/when reconstruction unproven |
| Causal identification | [Causal strategy](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/src/ai_karen_engine/core/reasoning/strategies/causal_strategy.py) abstains when no identified causal estimator exists | Correct fail-closed behavior; do not describe as live causal estimator |

**Important correction:** A diagnostic label naming `postgres_pgvector_fts` does not show that vector/FTS are used in `PostgresRecallRetriever`. The concrete SQL in that adapter relies on substring filtering. Investigate other paths before claiming pgvector is either operational or absent globally.

## Existing proof and empty benchmarks
- [Temporal claim tests](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/tests/architecture/test_memory_temporal_evolution.py) test half-open intervals, supersession, coexistence, contradictions and tenant mismatch.
- [Graph provenance tests](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/tests/core/memory/retrieval/test_graph_provenance_expansion.py) use a test graph stub: important contract, **not proof of live graph retrieval**.
- [Spreading activation unit tests](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/tests/core/memory/test_spreading_activation.py) verify decay/depth.
- The following benchmark files currently only contain `assert True`: [latency](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/tests/benchmarks/memory/test_recall_latency.py), [quality](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/tests/benchmarks/memory/test_recall_quality.py), [long-range](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/tests/benchmarks/memory/test_long_range_memory.py), [forgetting](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/tests/benchmarks/memory/test_selective_forgetting.py).

## Dependency baseline
[requirements.txt](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/requirements.txt) retains PostgreSQL/SQLAlchemy/asyncpg/Redis and explicitly forbids adding a graph/vector engine without a benchmark-backed ADR. Milvus/Elasticsearch memory integrations are retired/stubbed, though older deployment artifacts may remain. This baseline **does not prove operational services are stopped**.

## First audit tasks
1. Trace the memory entry point from ChatRuntime to NeuroRecall and inspect **executed SQL/queries**.
2. Verify pgvector extension, embeddings, index health, FTS config, candidate score source, RLS, erasure and tenant scope in an isolated live-Postgres test.
3. Check graph projection -> committed event lineage -> traversal -> NeuroRecall -> prompt evidence.
4. Replace empty benchmark tests with substantive measurements before comparing external techniques.


## KCR-01 executed-path research

See [KCR-01 retrieval lineage](KCR01_RETRIEVAL_LINEAGE.md) for the verified **memory_items pgvector/FTS vs memory_assertion substring recall** split, test scope, and live-PostgreSQL evidence gate.
